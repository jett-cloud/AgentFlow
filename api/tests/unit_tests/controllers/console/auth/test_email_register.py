"""Unit tests for email register controller endpoints."""

from __future__ import annotations

import base64
from unittest.mock import ANY, MagicMock, patch

from flask import Flask

from controllers.console.auth.email_register import (
    DevelopmentRegisterApi,
    EmailRegisterCheckApi,
    EmailRegisterResetApi,
    EmailRegisterSendEmailApi,
)
from services.feature_service import SystemFeatureModel


class TestEmailRegisterSendEmailApi:
    @patch("controllers.console.auth.email_register.AccountService.get_account_by_email_with_case_fallback")
    @patch("controllers.console.auth.email_register.AccountService.send_email_register_email")
    @patch("controllers.console.auth.email_register.BillingService.is_email_in_freeze")
    @patch("controllers.console.auth.email_register.AccountService.is_email_send_ip_limit", return_value=False)
    @patch("controllers.console.auth.email_register.extract_remote_ip", return_value="127.0.0.1")
    def test_send_email_normalizes_and_falls_back(
        self,
        mock_extract_ip,
        mock_is_email_send_ip_limit,
        mock_is_freeze,
        mock_send_mail,
        mock_get_account,
        app: Flask,
    ):
        mock_send_mail.return_value = "token-123"
        mock_is_freeze.return_value = False
        mock_account = MagicMock()
        mock_get_account.return_value = mock_account

        feature_flags = SystemFeatureModel(enable_email_password_login=True, is_allow_register=True)
        with (
            patch("controllers.console.auth.email_register.dify_config.BILLING_ENABLED", True),
            patch("controllers.console.wraps.dify_config.EDITION", "CLOUD"),
            patch("controllers.console.wraps.FeatureService.get_system_features", return_value=feature_flags),
        ):
            with app.test_request_context(
                "/email-register/send-email",
                method="POST",
                json={"email": "Invitee@Example.com", "language": "en-US"},
            ):
                response = EmailRegisterSendEmailApi().post()

        assert response == {"result": "success", "data": "token-123"}
        mock_is_freeze.assert_called_once_with("invitee@example.com")
        mock_send_mail.assert_called_once_with(email="invitee@example.com", account=mock_account, language="en-US")
        mock_extract_ip.assert_called_once()
        mock_is_email_send_ip_limit.assert_called_once_with("127.0.0.1")


class TestEmailRegisterCheckApi:
    @patch("controllers.console.auth.email_register.AccountService.reset_email_register_error_rate_limit")
    @patch("controllers.console.auth.email_register.AccountService.generate_email_register_token")
    @patch("controllers.console.auth.email_register.AccountService.revoke_email_register_token")
    @patch("controllers.console.auth.email_register.AccountService.add_email_register_error_rate_limit")
    @patch("controllers.console.auth.email_register.AccountService.get_email_register_data")
    @patch("controllers.console.auth.email_register.AccountService.is_email_register_error_rate_limit")
    def test_validity_normalizes_email_before_checks(
        self,
        mock_rate_limit_check,
        mock_get_data,
        mock_add_rate,
        mock_revoke,
        mock_generate_token,
        mock_reset_rate,
        app: Flask,
    ):
        mock_rate_limit_check.return_value = False
        mock_get_data.return_value = {"email": "User@Example.com", "code": "4321"}
        mock_generate_token.return_value = (None, "new-token")

        feature_flags = SystemFeatureModel(enable_email_password_login=True, is_allow_register=True)
        with (
            patch("controllers.console.wraps.dify_config.EDITION", "CLOUD"),
            patch("controllers.console.wraps.FeatureService.get_system_features", return_value=feature_flags),
        ):
            with app.test_request_context(
                "/email-register/validity",
                method="POST",
                json={"email": "User@Example.com", "code": "4321", "token": "token-123"},
            ):
                response = EmailRegisterCheckApi().post()

        assert response == {"is_valid": True, "email": "user@example.com", "token": "new-token"}
        mock_rate_limit_check.assert_called_once_with("user@example.com")
        mock_generate_token.assert_called_once_with(
            "user@example.com", code="4321", additional_data={"phase": "register"}
        )
        mock_reset_rate.assert_called_once_with("user@example.com")
        mock_add_rate.assert_not_called()
        mock_revoke.assert_called_once_with("token-123")


class TestEmailRegisterResetApi:
    @patch("controllers.console.auth.email_register.AccountService.reset_login_error_rate_limit")
    @patch("controllers.console.auth.email_register.AccountService.login")
    @patch("controllers.console.auth.email_register.EmailRegisterResetApi._create_new_account")
    @patch("controllers.console.auth.email_register.AccountService.get_account_by_email_with_case_fallback")
    @patch("controllers.console.auth.email_register.AccountService.revoke_email_register_token")
    @patch("controllers.console.auth.email_register.AccountService.get_email_register_data")
    @patch("controllers.console.auth.email_register.extract_remote_ip", return_value="127.0.0.1")
    def test_reset_creates_account_with_normalized_email(
        self,
        mock_extract_ip,
        mock_get_data,
        mock_revoke_token,
        mock_get_account,
        mock_create_account,
        mock_login,
        mock_reset_login_rate,
        app: Flask,
    ):
        mock_get_data.return_value = {"phase": "register", "email": "Invitee@Example.com"}
        mock_create_account.return_value = MagicMock()
        token_pair = MagicMock()
        token_pair.model_dump.return_value = {"access_token": "a", "refresh_token": "r"}
        mock_login.return_value = token_pair
        mock_get_account.return_value = None

        feature_flags = SystemFeatureModel(enable_email_password_login=True, is_allow_register=True)
        with (
            patch("controllers.console.wraps.dify_config.EDITION", "CLOUD"),
            patch("controllers.console.wraps.FeatureService.get_system_features", return_value=feature_flags),
        ):
            with app.test_request_context(
                "/email-register",
                method="POST",
                json={"token": "token-123", "new_password": "ValidPass123!", "password_confirm": "ValidPass123!"},
            ):
                response = EmailRegisterResetApi().post()

        assert response == {"result": "success", "data": {"access_token": "a", "refresh_token": "r"}}
        mock_create_account.assert_called_once_with(
            email="invitee@example.com",
            password="ValidPass123!",
            timezone=None,
            language=None,
        )
        mock_reset_login_rate.assert_called_once_with("invitee@example.com")
        mock_revoke_token.assert_called_once_with("token-123")
        mock_extract_ip.assert_called_once()

    @patch("controllers.console.auth.email_register.set_csrf_token_to_cookie")
    @patch("controllers.console.auth.email_register.set_refresh_token_to_cookie")
    @patch("controllers.console.auth.email_register.set_access_token_to_cookie")
    @patch("controllers.console.auth.email_register.AccountService.login")
    @patch("controllers.console.auth.email_register.AccountService.create_account_and_tenant")
    @patch("controllers.console.auth.email_register.AccountService.get_account_by_email_with_case_fallback")
    @patch("controllers.console.auth.email_register.extract_remote_ip", return_value="127.0.0.1")
    def test_register_creates_isolated_account_and_cookie_session(
        self,
        mock_extract_ip,
        mock_get_account,
        mock_create_account,
        mock_login,
        mock_set_access_cookie,
        mock_set_refresh_cookie,
        mock_set_csrf_cookie,
        app: Flask,
    ):
        mock_get_account.return_value = None
        account = MagicMock()
        mock_create_account.return_value = account
        mock_login.return_value = MagicMock(
            access_token="access",
            refresh_token="refresh",
            csrf_token="csrf",
        )
        feature_flags = SystemFeatureModel(enable_email_password_login=True, is_allow_register=True)
        password = base64.b64encode(b"ValidPass123!").decode()

        with (
            patch("controllers.console.auth.email_register.dify_config.ALLOW_REGISTER", True),
            patch("controllers.console.auth.email_register.dify_config.ALLOW_DEV_NO_EMAIL_REGISTER", True),
            patch("controllers.console.wraps.dify_config.EDITION", "CLOUD"),
            patch("controllers.console.wraps.FeatureService.get_system_features", return_value=feature_flags),
            app.test_request_context(
                "/register",
                method="POST",
                json={
                    "email": "User@Example.com",
                    "name": "User",
                    "password": password,
                    "language": "zh-Hans",
                    "timezone": "Asia/Shanghai",
                },
            ),
        ):
            response = DevelopmentRegisterApi().post()

        assert response.get_json() == {"result": "success"}
        mock_create_account.assert_called_once_with(
            email="user@example.com",
            name="User",
            password="ValidPass123!",
            interface_language="zh-Hans",
            timezone="Asia/Shanghai",
            session=ANY,
        )
        mock_login.assert_called_once_with(account=account, session=ANY, ip_address="127.0.0.1")
        mock_set_access_cookie.assert_called_once()
        mock_set_refresh_cookie.assert_called_once()
        mock_set_csrf_cookie.assert_called_once()
        mock_extract_ip.assert_called_once()

    @patch("controllers.console.auth.email_register.AccountService.reset_login_error_rate_limit")
    @patch("controllers.console.auth.email_register.AccountService.login")
    @patch("controllers.console.auth.email_register.EmailRegisterResetApi._create_new_account")
    @patch("controllers.console.auth.email_register.AccountService.get_account_by_email_with_case_fallback")
    @patch("controllers.console.auth.email_register.AccountService.revoke_email_register_token")
    @patch("controllers.console.auth.email_register.AccountService.get_email_register_data")
    @patch("controllers.console.auth.email_register.extract_remote_ip", return_value="127.0.0.1")
    def test_reset_passes_timezone_to_new_account(
        self,
        mock_extract_ip,
        mock_get_data,
        mock_revoke_token,
        mock_get_account,
        mock_create_account,
        mock_login,
        mock_reset_login_rate,
        app: Flask,
    ):
        mock_get_data.return_value = {"phase": "register", "email": "Invitee@Example.com"}
        mock_create_account.return_value = MagicMock()
        token_pair = MagicMock()
        token_pair.model_dump.return_value = {"access_token": "a", "refresh_token": "r"}
        mock_login.return_value = token_pair
        mock_get_account.return_value = None

        feature_flags = SystemFeatureModel(enable_email_password_login=True, is_allow_register=True)
        with (
            patch("controllers.console.wraps.dify_config.EDITION", "CLOUD"),
            patch("controllers.console.wraps.FeatureService.get_system_features", return_value=feature_flags),
        ):
            with app.test_request_context(
                "/email-register",
                method="POST",
                json={
                    "token": "token-123",
                    "new_password": "ValidPass123!",
                    "password_confirm": "ValidPass123!",
                    "timezone": "Asia/Shanghai",
                },
            ):
                response = EmailRegisterResetApi().post()

        assert response == {"result": "success", "data": {"access_token": "a", "refresh_token": "r"}}
        mock_create_account.assert_called_once_with(
            email="invitee@example.com",
            password="ValidPass123!",
            timezone="Asia/Shanghai",
            language=None,
        )
        mock_reset_login_rate.assert_called_once_with("invitee@example.com")
        mock_revoke_token.assert_called_once_with("token-123")
        mock_extract_ip.assert_called_once()

    @patch("controllers.console.auth.email_register.AccountService.reset_login_error_rate_limit")
    @patch("controllers.console.auth.email_register.AccountService.login")
    @patch("controllers.console.auth.email_register.EmailRegisterResetApi._create_new_account")
    @patch("controllers.console.auth.email_register.AccountService.get_account_by_email_with_case_fallback")
    @patch("controllers.console.auth.email_register.AccountService.revoke_email_register_token")
    @patch("controllers.console.auth.email_register.AccountService.get_email_register_data")
    @patch("controllers.console.auth.email_register.extract_remote_ip", return_value="127.0.0.1")
    def test_reset_passes_language_to_new_account(
        self,
        mock_extract_ip,
        mock_get_data,
        mock_revoke_token,
        mock_get_account,
        mock_create_account,
        mock_login,
        mock_reset_login_rate,
        app: Flask,
    ):
        mock_get_data.return_value = {"phase": "register", "email": "Invitee@Example.com"}
        mock_create_account.return_value = MagicMock()
        token_pair = MagicMock()
        token_pair.model_dump.return_value = {"access_token": "a", "refresh_token": "r"}
        mock_login.return_value = token_pair
        mock_get_account.return_value = None

        feature_flags = SystemFeatureModel(enable_email_password_login=True, is_allow_register=True)
        with (
            patch("controllers.console.wraps.dify_config.EDITION", "CLOUD"),
            patch("controllers.console.wraps.FeatureService.get_system_features", return_value=feature_flags),
        ):
            with app.test_request_context(
                "/email-register",
                method="POST",
                json={
                    "token": "token-123",
                    "new_password": "ValidPass123!",
                    "password_confirm": "ValidPass123!",
                    "language": "zh-Hans",
                },
            ):
                response = EmailRegisterResetApi().post()

        assert response == {"result": "success", "data": {"access_token": "a", "refresh_token": "r"}}
        mock_create_account.assert_called_once_with(
            email="invitee@example.com",
            password="ValidPass123!",
            timezone=None,
            language="zh-Hans",
        )
        mock_reset_login_rate.assert_called_once_with("invitee@example.com")
        mock_revoke_token.assert_called_once_with("token-123")
        mock_extract_ip.assert_called_once()
