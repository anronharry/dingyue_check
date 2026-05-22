# Contributing

感谢你愿意为这个项目做贡献。

## Before You Start

请先确保：

- 你已经阅读过 [README.md](README.md)
- 你的修改目标是明确的，最好先开 Issue 或在 PR 描述里写清楚
- 不要提交真实的订阅链接、Token、用户隐私数据或 `.env`

## Development Setup

推荐使用 Python 3.12。项目支持 Python 3.10、3.11、3.12，暂不支持 Python 3.13。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements-dev.txt
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## Validation

提交前至少运行：

```bash
python -m compileall app core handlers renderers services shared tests web main.py
python -m pytest -q
python -m ruff check .
```

`python -m ruff format --check .` 当前尚未作为全仓门禁启用；仓库仍有历史格式差异。新增或修改 Python 文件时，请对相关文件运行 `python -m ruff format <path>`。

后端测试应在 60 秒内完成。若测试卡住，请暴露并修复根因，不要通过跳过测试、降低断言或吞掉异常来制造通过结果。

## Contribution Expectations

- 保持改动聚焦，不要把无关重构混在一个 PR 里
- 新增逻辑尽量补测试
- 不要把错误处理重新改成依赖中文文案匹配
- 不接受静默 fallback、隐式降级或隐藏真实错误的兼容路径
- 不接受 mock 假成功、模拟成功输出或绕过真实执行的测试捷径
- 不要提交真实 token、真实订阅链接、凭据、用户隐私数据或 `.env`
- 不要提交运行数据、测试垃圾目录或本地私有说明文件
- 新增用户可见文本请使用正常 UTF-8 编码

## Pull Request Checklist

- 功能或修复目标清晰
- PR 只解决一类问题，没有混入无关重构
- 测试、lint 和 compile 检查已通过
- README、CHANGELOG 或注释在必要时已同步更新
- 没有提交敏感文件、真实订阅链接或本地运行产物

## Bug Reports

报告问题时请提供：

- Python 版本、操作系统和启动方式
- 触发问题的命令或 Web Admin 路径
- 去除 Token、订阅链接和用户隐私后的错误日志
- 你已经运行过的本地验证命令及结果

## Release Notes

维护者发布版本前应更新 `CHANGELOG.md`，从干净工作区运行完整验证命令，并确认没有 `.env`、真实 Token、订阅链接、导出缓存、日志或本地运行数据被暂存。
