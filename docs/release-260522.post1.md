# U-DynamicLight 260522.post1

## 修复

- 修复前一个玩家静止时，后续玩家的动态光源不更新。
- 经过草、蕨类、高花和水边时，在有限范围内寻找空气位置放置客户端光源；不替换植物、水或服务器方块。
- 改善光源移动和亮度切换，定期恢复被普通方块/区块数据覆盖的静止光源。
- 修复跨维度、退出、重新加入和停用时的旧光源状态清理。
- `/ud` 刷新间隔保存后立即生效；保存或调度失败可重试，并保留之前的有效设置。

## 安装与兼容性

- 将 `endstone_u_dynamic_light-260522.post1-py3-none-any.whl` 放入服务器的 `plugins` 目录，移除旧版本插件 wheel 后重启。保留现有配置和语言文件。
- Python 3.11–3.15；依赖固定为实际测试的 `mcbe-binarystream==2.1.0`。
- Endstone API 0.11；沿用协议 944+（Bedrock 1.26.14+）的有符号 XYZ 数据格式，不支持旧版无符号 Y 协议。
- 仍为仅持有者自己可见的动态光源；不会让其他玩家看到该持有者的光，也不会修改服务端地图方块。
- 完全淹没或封闭且附近无空气时不会产生光；未知自定义方块不会被当作可穿透方块。

## Verification

Release CI builds a universal wheel, verifies its metadata, and installs the same wheel with the real serializer dependency on Python 3.11, 3.12, 3.13, 3.14, and 3.15. All 30 regression tests must pass on every interpreter before publication. SHA256SUMS accompanies the wheel and source distribution.

Tests use an Endstone API double and do not replace a live Bedrock client/server test. No server deployment is included. Check rendering, chunk arrival, custom world heights, and real Endstone/Python packaging with the [in-game checklist](https://github.com/ReallocAll/U_DynamicLight/blob/v260522.post1/docs/dynamic-light-verification.md) before broad rollout. Complete flicker removal is not claimed.
