export function shouldConnectContainerStart({
  parentId,
  startId,
  connectionSourceId,
} = {}) {
  return Boolean(parentId && startId && !connectionSourceId)
}
