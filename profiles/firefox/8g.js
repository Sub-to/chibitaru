// 8GB プロファイル — 余裕がある側。
//
// ここでは Fission（サイト分離）を切らない。サイトごとにプロセスを分ける
// この仕組みは、悪意のあるサイトが他サイトのメモリを覗く類の攻撃に対する
// 実質的な防御になっている。RAM に余裕がある機体で外す理由はない。
// 予算 900MB はプロセス数の上限と履歴キャッシュの縮小で狙う。

// dom.ipc.processCount は置かない。Fission がオンだと無視されるため。
// 実測で 15→15 とプロセス数が 1 つも変わらないことを確認した。

// ── メモリ回収 ──────────────────────────────────────────
// 空きが減ったら見ていないタブを捨てる（開き直せば復帰する）
user_pref("browser.tabs.unloadOnLowMemory", true);
// 「戻る」用に保持する描画済みページ数。既定は搭載量から自動算出で最大 8。
user_pref("browser.sessionhistory.max_total_viewers", 2);
// セッション復元の書き込み間隔を延ばす（既定 15 秒）
user_pref("browser.sessionstore.interval", 60000);

// ── 先読みをやめる ──────────────────────────────────────
user_pref("network.prefetch-next", false);
user_pref("network.dns.disablePrefetch", true);
user_pref("network.predictor.enabled", false);

// 動画・描画のハードウェア設定は _hardware.js にある。
// 箱に GPU がなく、ここに置くとベンチが逆の結果を出すため分離した。
