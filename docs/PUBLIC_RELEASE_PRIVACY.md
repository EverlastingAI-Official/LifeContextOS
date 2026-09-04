# Public release privacy boundary

This repository is a source-only distribution. The public tree intentionally excludes:

- raw life documents and conversation exports;
- local Archive, Evidence, ThoughtCells, profiles, oral-history answers, and conversation memory;
- SOUL, MEMORY, and STYLE files derived from a real person;
- voice recordings, voice embeddings, and consent records;
- API keys, `.env` files, cloud-provider configuration, and runtime logs;
- local model weights, CosyVoice weights, Python environments, and downloaded runtimes;
- backups, caches, and the private repository history.

The files in `FENJUEskill/` and `examples/persona-template/` are blank schemas. They do not describe a real person.

## Before every public push

1. Run `scripts/audit_public_tree.py` from the repository root.
2. Inspect `git status --short` and `git diff --cached`.
3. Confirm that `RAWDATA/` and `data/` contain only their README files.
4. Confirm that no audio, model weight, archive, backup, or secret file is staged.
5. Use fictional, anonymized, or explicitly licensed data in tests and screenshots.
6. Treat the Git history as public data; removing a secret from the latest commit is not sufficient.

This automated audit is a safety net, not proof that a release contains no personal information. Human review remains required.
