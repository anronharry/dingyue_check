# Security Policy

## Supported Usage

这是一个面向自部署场景的 Telegram 机器人项目。

出于安全考虑，请不要在公开渠道提交：

- 真实订阅链接
- Telegram Bot Token
- `.env` 文件内容
- 备份 ZIP
- 导出的 YAML / TXT / JSON 中的敏感内容

## Reporting a Vulnerability

如果你发现了安全问题，建议：

1. 不要公开提交包含敏感细节的 Issue。
2. 联系仓库维护者，私下说明问题影响、复现方式和建议修复方案。
3. 在修复发布前，避免公开传播可直接利用的细节。

## Scope

比较值得优先报告的问题包括：

- 权限绕过
- 未授权导出或删除他人缓存
- 敏感信息泄露
- 备份恢复链路中的越权或路径问题
- 会导致大面积拒绝服务的输入处理缺陷
