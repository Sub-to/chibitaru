// 4GB プロファイル
//
// ── 実測で分かったこと（2026-08-23, 3ページ / 各3回 / 中央値）──
//
//   調整なし                    827MB  15プロセス
//   調整あり + Fission オフ     770MB  11プロセス
//   調整あり + Fission オン     800MB  15プロセス   ← これを採る
//
// 当初は Fission（サイト分離）を切る前提だった。プロセス数が
// 15→11 に減るので効きそうに見えたが、実際に減ったのは 30MB。
// 4GB 機の 0.7% にすぎない。
//
// Fission は、悪意のあるサイトが投機実行を使って他サイトのメモリを
// 読む類の攻撃に対する主要な防御になっている。それを 30MB で
// 売り渡すのは割に合わないと判断して、オンのまま残す。
//
// プロセス数が減ってもメモリが減らないのは、メモリを食っているのが
// プロセスの器ではなくページの中身だから。ここは PSS で数えて初めて
// 見える差で、プロセス数を指標にすると判断を間違える。
//
// dom.ipc.processCount は書いていない。Fission がオンだとサイトごとに
// プロセスが作られるため、この上限は無視される（8g で 15→15 のまま
// 変わらないことを実測で確認した）。効かない設定は置かない。

// ── メモリ回収 ──────────────────────────────────────────
// 空きが減ったら見ていないタブを捨てる（選び直せば読み込み直す）
user_pref("browser.tabs.unloadOnLowMemory", true);
user_pref("browser.low_commit_space_threshold_mb", 400);
// 「戻る」用に描画済みページを保持しない
user_pref("browser.sessionhistory.max_total_viewers", 0);
user_pref("browser.sessionstore.interval", 120000);

// ── 先読みをやめる ──────────────────────────────────────
user_pref("network.prefetch-next", false);
user_pref("network.dns.disablePrefetch", true);
user_pref("network.predictor.enabled", false);

// 動画・描画のハードウェア設定は _hardware.js にある。
// 箱に GPU がなく、ここに置くとベンチが逆の結果を出すため分離した。
