import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('shuttlescope', {
  version: process.env.npm_package_version ?? '1.0.0',
  platform: process.platform,
  openVideoFile: (): Promise<string | null> => ipcRenderer.invoke('open-video-file'),
})
