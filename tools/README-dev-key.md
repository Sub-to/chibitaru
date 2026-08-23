# tools/dev-key.pub について

母艦（開発機）から T440s 実機へ SSH で入るための**公開鍵**。
コンソールで 68 文字の base64 を手打ちするのが現実的でなかったため、
リポジトリ経由で渡せるように置いてある。

公開鍵なので、これが見えても他人が入れるようにはならない。
対になる秘密鍵は母艦から出ない。

実機で使うとき:

```bash
mkdir -p /root/.ssh && chmod 700 /root/.ssh
curl -fsSL https://raw.githubusercontent.com/Sub-to/chibitaru/os-v2/tools/dev-key.pub \
  >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
```

**開発が終わったら消すこと。** 実機側は
`/root/.ssh/authorized_keys` から該当行を削除、
リポジトリ側はこのファイルごと削除でよい。
