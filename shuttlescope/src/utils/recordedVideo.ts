/**
 * 録画の保存後に、試合へ動画パスを付ける更新 (S-16)。
 *
 * 録画ファイル自体は既に保存済みなので、この更新が失敗しても保存は成功のまま。
 * ただし失敗を黙って捨てると「試合に動画が付いた」と思い込むので、必ず通知する。
 */
export async function attachRecordedVideoPath(
  matchId: string | number,
  savedPath: string,
  deps: {
    put: (url: string, body: Record<string, unknown>) => Promise<unknown>
    onAttached: () => void
    onError: (err: unknown) => void
  },
): Promise<boolean> {
  try {
    await deps.put(`/matches/${matchId}`, {
      video_local_path: `localfile:///${savedPath}`,
      video_url: '',
    })
  } catch (err) {
    deps.onError(err)
    return false
  }
  deps.onAttached()
  return true
}
