// 実機でのみ適用する設定。GPU があることが前提。
//
// ⚠ ベンチマークの箱には GPU がない（libEGL がない）。そこでこれを
// 入れると WebRender がソフトウェア描画に落ち、描画バッファを抱えて
// 「調整したのに増える」という逆の結果になる。実際に 4g で +110MB、
// 8g で +173MB の逆行が出た。
//
// そのため tools/firefox-bench.sh はこのファイルを適用しない。
// 効果は実機で VA-API が効いているかどうかで確認すること:
//   about:support の「デコード」欄が hardware になっていれば効いている。

// ── 動画のハードウェアデコード ──────────────────────────
// これが効かないと再生が CPU に落ち、発熱と消費電力が跳ね上がる。
// この OS の目的からすると、メモリより優先度が高い項目。
user_pref("media.ffmpeg.vaapi.enabled", true);
user_pref("media.hardware-video-decoding.force-enabled", true);

// ── 描画 ────────────────────────────────────────────────
// GPU がある機体では WebRender のほうが軽く滑らか。
// 古い GPU で描画が壊れる場合はこの行を消す。
user_pref("gfx.webrender.all", true);
