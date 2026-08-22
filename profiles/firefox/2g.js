// 2GB プロファイル — いちばん厳しい側。
//
// 4g.js の実測（Fission を切っても 30MB しか減らない）を受けて、
// ここでもサイト分離は切らない。搭載量が少ない機体ほど、
// 防御を落とした状態で使い続ける危険は大きい。
//
// この容量では「タブを何枚も開いたまま」が成立しない。
// 見ていないタブは積極的に捨てる設定にしてある。タブは残り、
// 選び直せば読み込み直される。遅くはなるが、固まるよりましという判断。

// ── メモリ回収（4g より積極的）──────────────────────────
user_pref("browser.tabs.unloadOnLowMemory", true);
user_pref("browser.low_commit_space_threshold_mb", 300);
user_pref("browser.sessionhistory.max_total_viewers", 0);
user_pref("browser.sessionstore.interval", 300000);
user_pref("browser.sessionstore.max_tabs_undo", 2);

// ── 画像・描画のキャッシュを絞る ────────────────────────
// 表示していない画像のデコード結果を持ち続けない
user_pref("image.mem.discardable", true);
user_pref("browser.cache.memory.capacity", 32768);   // 32MB 上限

// ── 先読みをやめる ──────────────────────────────────────
user_pref("network.prefetch-next", false);
user_pref("network.dns.disablePrefetch", true);
user_pref("network.predictor.enabled", false);

// 動画・描画のハードウェア設定は _hardware.js にある。
// 箱に GPU がなく、ここに置くとベンチが逆の結果を出すため分離した。
