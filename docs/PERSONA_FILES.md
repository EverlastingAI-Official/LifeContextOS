# SOUL / MEMORY / STYLE 人格文件设计

参考 `digital-immortality` 的人格文件方法，中台保留 Markdown 作为可读、可编辑、可迁移的人格载体，同时增加证据引用、版本和审核状态。

## 三个文件的职责

- `SOUL.md`：稳定身份、自我叙事、价值观、决策原则与代理权限边界。
- `MEMORY.md`：经审核的关系、情境、决策和洞察记忆；允许增长，但不能悄悄改写历史。
- `STYLE.md`：写作、说话、修辞、情绪与场景差异；每条风格结论都应回到真实样本。

原项目中的 `lifecontext.md` 与 `thoughtcell.md` 不应消失，而应进入中台结构化数据库；三个人格文件是从数据库编译出的 Mindcopy 视图。`skill.md` 则属于 Agent 能力与授权系统，不属于人格本身。

## 编译方向

```text
Evidence + LifeContext + ThoughtCell
              ↓ 人工审核
       SOUL / MEMORY / STYLE
              ↓ 版本签名
          Mindcopy Runtime
```

运行时不得把一次模型输出直接追加进 SOUL。模型交互先进入隔离区，经过来源判断与用户确认后，才可进入 MEMORY；稳定重复出现的模式才可能晋升为 SOUL 或 STYLE。

## 与原项目相比的关键增强

- 事实、解释和模型生成内容分层；
- 每条重要人格结论附证据；
- 人格文档有版本、差异和回滚；
- Strict Sync 与 Self-Evolution 使用不同命名空间；
- 工具权限不因“像本人”而自动获得；
- 支持机器可读 Schema，同时保留 Markdown 的人文可读性。
