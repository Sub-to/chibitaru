# Claude Code を入れる

```
su - subrigun -c 'bash /opt/chibitaru/install/claude-cli.sh'
```

node は要らない。公式の入れ方に **native** があり、単体で動く実行
ファイルが置かれる（207MB）。node を入れると 100MB 以上増えるうえ、
この OS では他に使い道がない。

## 一度目に入らなかった理由

**入っていた。居場所が見えなくなっていただけだった。**

- `~/.local/bin/claude` はあり、`--version` も通っていた
- しかし `which claude` は何も返さなかった

原因は**この OS が自分で作った落とし穴**。

bash は `~/.bash_profile` があると `~/.profile` を読まない。
Debian が PATH に `~/.local/bin` を足しているのは `~/.profile` のほう。
この OS は tty1 で画面を起こすために `~/.bash_profile` を置いたので、
`~/.profile` が読まれなくなり、`~/.local/bin` が PATH から消えていた。

```bash
# ~/.bash_profile の先頭でこれを読む
[ -r "$HOME/.profile" ] && . "$HOME/.profile"
```

`install/setup.sh` の session 段でもこう書くようにした。
`~/.local/bin` に入れるものは他にもあるので、ここを塞いでおかないと
同じことが何度でも起きる。

> 「入らなかった」と言われた時、まず**本当に入っていないのか**を
> 確かめること。今回は入っていた。無いのは PATH のほうだった。

## ログイン

**こちらではしない。** 合言葉や鍵を扱わない。

下のシェルで `claude` と打って、画面の案内どおりに進める。

## 自動更新

`autoUpdates: false` になっている。テザリングで 200MB を勝手に
落とされると困るので、そのままにしてある。上げたい時は自分で
`claude update`。
