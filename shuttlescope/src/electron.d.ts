export {}

declare global {
  interface Window {
    shuttlescope: {
      version: string
      platform: string
      openVideoFile: () => Promise<string | null>
    }
  }
}
