# dsh-customization

适用于 Linux 上 **DeepSeek Harness（DSH）0.1.5-rc.2** 的可复现定制安装器。

它把 profile 配置、全局工程指令、插件版本和少量框架补丁整理成一条可检查、可重复执行的安装流程。所有框架文件在修改前都会校验 SHA-256；版本或文件内容不匹配时立即停止，不会猜测性套用补丁。

## 功能

- 将新会话的默认权限预设设为 `danger-full-access`。
- 安装简洁的全局 `AGENTS.md` 工程规则。
- 为 `default` 和 `headless` profile 设置统一的执行型 Persona。
- 为 Web profile 固定安装：
  - [`dsh-infinite-gen-4`](https://github.com/Minglink/dsh-infinite-gen-4)
  - [`dsh-rewind-plugin`](https://github.com/SiriLee/dsh-rewind)
- 使用锁文件固定两个 Web 插件的 Git 提交和完整性哈希。
- 加载 `instruction-hygiene.mjs`：仅当 Infinite Gen 的第二段强化提示与第一段完全相同时删除重复段；内容不同时原样保留。
- 调整四个内置 Agent Persona、workspace instruction 提示和 approval runtime context。
- 让 `minimal` preset 也加载全局/项目 AGENTS，并保留权限等 runtime context。

## 兼容性

当前发布只支持：

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Linux |
| DSH | `0.1.5-rc.2` |
| Python | 3.10+ |
| Node.js | DSH 支持的版本 |
| 其他命令 | `patch`、`pnpm` |

安装器不会为其他 DSH 版本保留兼容层。升级 DSH 后，应针对新版本重新审计并更新哈希与补丁。

## 快速开始

```bash
git clone https://github.com/qiuham/dsh-customization.git
cd dsh-customization

# 查看当前状态
python3 dsh_customization.py --status

# 应用定制
python3 dsh_customization.py --apply

# 检查 Web profile 的组合结果
dsh --profile web --dump-config
```

默认使用 PATH 中的 `dsh`，并读取 `$DSH_HOME`；未设置时使用 `~/.dsh`。

也可以显式指定路径：

```bash
python3 dsh_customization.py --status \
  --dsh-package /path/to/lib/node_modules/@deepseek-ai/dsh \
  --dsh-home /path/to/.dsh
```

## 安装过程

`--apply` 会按以下顺序执行：

1. 确认 DSH 版本为 `0.1.5-rc.2`。
2. 校验八个框架目标文件的原始或已修改 SHA-256。
3. 在 `$DSH_HOME/.dsh-customization-backup` 保存受管理文件的原始内容。
4. 原子写入 profile 配置、全局 AGENTS、提示词卫生插件和框架补丁。
5. 写入固定的 `package.json` 与 `pnpm-lock.yaml`。
6. 运行 `pnpm install --frozen-lockfile`。

如果目标文件来自未知构建，脚本会在写入前停止。

## Profile 行为

### default / headless

两个 profile 保留各自原生工具组合，同时使用相同的精简执行 Persona。它们仍由 DSH 原生的 `agent-instructions` 加载全局与项目级 AGENTS。

### web

Web profile 默认使用 `standard` preset，并加载两个固定版本的插件。提示词卫生插件通过 DSH 的 `system-prompt/assemble` 扩展点处理完全相同的重复段，而不是修改第三方插件源码。

### minimal

`minimal` 仍是 complete Persona 和单一持久 shell 的精简模式，但现在也加载：

```yaml
- id: agent-instructions
  config:
    maxBytes: 65536
```

同时保留 runtime context，使当前权限和其他动态状态仍能进入模型上下文。

## 状态检查

```bash
python3 dsh_customization.py --status
```

输出包括：

- 八个框架文件是 `original`、`modified` 还是 `unknown`；
- 本地备份是否存在；
- `permission.defaultPreset` 状态；
- 每个用户级配置文件是 `configured` 还是 `drifted`。

## 验证

```bash
python3 -m unittest -v test_customization.py
python3 dsh_customization.py --status
```

测试覆盖：

- 从原始 DSH 文件应用八个补丁；
- 在独立副本中逐文件恢复原始状态；
- 遇到未知文件哈希时在修改前停止；
- `default`、`headless`、Web profile 和本地插件文件的生成；
- 只删除内容完全一致的 Infinite Gen 重复提示段。

## 恢复受管理文件

安装时生成的备份可用于恢复：

```bash
python3 dsh_customization.py --rollback
```

恢复前会验证受管理文件仍与安装后的哈希一致；检测到后续人工修改时会停止，避免覆盖新内容。

## 目录结构

```text
dsh_customization.py   安装、状态检查和恢复入口
framework-manifest.json
patches/               SHA-256 绑定的框架补丁
templates/             AGENTS、profile、插件和锁文件模板
test_customization.py  隔离副本测试
```

## 设计原则

- 优先使用 DSH 的 profile、Persona、AGENTS 和 system prompt 扩展接口。
- 需要修改安装包文件时，只接受精确版本和精确哈希。
- 不增加跨版本兼容层，也不自动迁移未知版本。
- 不读取或提交本机凭据、模型密钥和完整用户 settings。
- 配置漂移明确显示为 `drifted`，不静默覆盖。
