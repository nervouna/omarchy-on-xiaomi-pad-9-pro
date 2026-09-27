# keys/ (git-ignored)

`loa_shuntian` / `loa_shuntian.pub`: your SSH key, used by `tools/tssh`. The repo
ships no key. Create one with `ssh-keygen -t ed25519 -N '' -f keys/loa_shuntian`;
`tools/apply-overlay.sh` adds `keys/*.pub` to root's `authorized_keys` on the tablet.
