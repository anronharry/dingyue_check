# Contributing

感谢你愿意为这个项目做贡献。

## Before You Start

请先确保：

- 你已经阅读过 [README.md](README.md)
- 你的修改目标是明确的，最好先开 Issue 或在 PR 描述里写清楚
- 不要提交真实的订阅链接、Token、用户隐私数据或 `.env`

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

Windows:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -U pip
pip install -r requirements.txt
```

## Validation

提交前至少运行：

```bash
pytest -q
```

如涉及装配或导入结构调整，建议再运行：

```bash
python -m compileall app core handlers renderers services shared tests
```

## Contribution Expectations

- 保持改动聚焦，不要把无关重构混在一个 PR 里
- 新增逻辑尽量补测试
- 不要把错误处理重新改成依赖中文文案匹配
- 不要提交运行数据、测试垃圾目录或本地私有说明文件
- 新增用户可见文本请使用正常 UTF-8 编码

## Pull Request Checklist

- 功能或修复目标清晰
- 测试已通过
- README 或注释在必要时已同步更新
- 没有提交敏感文件或本地运行产物
