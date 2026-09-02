export function filesArrayToMap(files) {
  return Object.fromEntries(files.map(file => [file.path, file.content]))
}

export function filesMapToArray(files) {
  return Object.entries(files).map(([path, content]) => ({ path, content }))
}
