import {
  fetchPluginInstallTask,
  installPluginsFromMarketplace,
} from '@/features/integrations/api/difyPluginsApi.js'
import {
  extractInstallTaskId,
  waitForPluginInstallTask,
} from '../tool-plugin/pluginInstallHelpers.js'

export async function installMarketplacePackage(latestPackageIdentifier) {
  if (!latestPackageIdentifier)
    throw new Error('缺少插件包标识')
  const result = await installPluginsFromMarketplace([latestPackageIdentifier])
  const taskId = extractInstallTaskId(result)
  if (taskId)
    await waitForPluginInstallTask(fetchPluginInstallTask, taskId)
  return result
}
