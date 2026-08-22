// 全ティア共通。初回起動時のウェルカムタブやテレメトリを止める。
//
// ベンチマークでは「調整なし」の側にもこれを入れる。入れないと調整なし
// だけが余分なタブを開くことになり、比較が不公平になるため。

// ── 初回起動の余計なページ ──────────────────────────────
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.aboutwelcome.enabled", false);
user_pref("datareporting.policy.firstRunURL", "");
user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);
user_pref("browser.shell.checkDefaultBrowser", false);

// ── テレメトリ・データ送信 ──────────────────────────────
user_pref("toolkit.telemetry.enabled", false);
user_pref("toolkit.telemetry.unified", false);
user_pref("toolkit.telemetry.archive.enabled", false);
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("browser.newtabpage.activity-stream.feeds.telemetry", false);
user_pref("browser.newtabpage.activity-stream.telemetry", false);
user_pref("app.shield.optoutstudies.enabled", false);
