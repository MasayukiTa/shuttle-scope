# Electron DRM サポートの選択肢

通常版 (`electron`): デフォルト、Widevine DRM 非対応。

## DRM が必要な場合

通常 `electron` を castlabs 版に差し替える:
```json
"electron": "github:castlabs/electron-releases#<VERSION>+wvcus"
```

- 利用可能バージョン: https://github.com/castlabs/electron-releases/releases
- 現在の `electron@^39.8.5` に対応するバージョンが存在しない場合、ダウングレードが必要。
- 切り替え後、`npm install` で github tarball を取得。

> ⚠️ 過去 `package.json` に `_castlabs_drm_note` という擬似パッケージ名でこの note を埋め込んでいたが、
> npm のパッケージ命名規約 (アンダースコア始まり禁止) で `npm ci` が EINVALIDPACKAGENAME で fail
> していたためここに移動した (commit で削除)。
