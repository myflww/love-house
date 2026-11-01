"""Build a private, reviewable AstrBot configuration; never inspect a host install.

Paths belong to the machine running MemoryHost, which must share its filesystem
with AstrBot. The management session and explicit UI ownership confirmation are
unchanged. The generated artifact contains UMO identifiers, never source tokens.
"""
from ..errors import ValidationError
from .source_client import SourceClientError, validate_platforms, _write_private_json

PLUGIN_DIRECTORY = 'astrbot_plugin_love_house'
CONFIG_FILENAME = PLUGIN_DIRECTORY + '_config.json'


def validate_setup(data):
    if not isinstance(data, dict) or set(data) != {'same_machine', 'platform', 'allowed_umos'}:
        raise ValidationError('AstrBot 配置须包含运行位置、平台和 /sid 名单')
    if data['same_machine'] is not True:
        raise ValidationError('请在 AstrBot 所在机器运行爱之屋服务并生成配置；本机文件路径不能用于另一台服务器或容器')
    platform = data['platform']
    try:
        if platform == '*':raise SourceClientError('请选择明确的平台')
        validate_platforms([platform])
    except SourceClientError:
        raise ValidationError('请选择明确的平台标识，例如 qq；QQ 适配器 aiocqhttp 使用 qq') from None
    umos = data['allowed_umos']
    if not isinstance(umos, list) or not 1 <= len(umos) <= 2000:
        raise ValidationError('请在目标私聊或群聊发送 /sid，并逐行填入返回的完整 UMO')
    for umo in umos:
        if not isinstance(umo, str) or len(umo) > 500 or any(c.isspace() or ord(c) < 32 for c in umo):
            raise ValidationError('/sid 名单含无效字符；只填完整 UMO，不填聊天正文')
        try:umo.encode('utf-8')
        except UnicodeError:raise ValidationError('/sid 含无法保存的字符，请重新复制 UMO') from None
        parts = umo.split(':', 2)
        if len(parts) != 3 or not parts[0] or parts[1] not in ('FriendMessage', 'GroupMessage', 'OtherMessage') or not parts[2]:
            raise ValidationError('/sid 应为 平台实例:消息类型:会话标识；不要把平台 qq 当成实例名猜填')
    if len(set(umos)) != len(umos):
        raise ValidationError('/sid 名单有重复项，请保留一份')
    return {'same_machine': True, 'platform': platform, 'allowed_umos': list(umos)}


def build_setup(registry, source_id, data, *, base_url=None):
    data = validate_setup(data)
    source = registry.get(source_id)
    if source['adapter'] != 'astrbot' or source['revoked'] or not source['enabled']:
        raise ValidationError('请先选择已启用且未撤销的 AstrBot 活动来源')
    if data['platform'] not in source['platforms'] and '*' not in source['platforms']:
        raise ValidationError('插件平台不在此来源允许范围内，请核对来源配置')
    # configuration() refreshes and validates the source's fixed identity on
    # this server. It returns a path, never a credential in this response.
    bundle = registry.configuration(source_id, base_url=base_url)
    config = {'enabled': True, 'record_scheduled_outputs': False, 'record_observations': True,
              'bindings': [{'runtime_agent_id': source['runtime_agent_id'],
                            'source_config_path': bundle['private_path'],
                            'allowed_umos': data['allowed_umos'], 'platform': data['platform']}]}
    directory = registry.directory / 'astrbot-setup' / source_id
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    path = directory / CONFIG_FILENAME
    _write_private_json(path, config)
    return {**bundle, 'astrbot_setup': {
        'config': config, 'config_path': str(path), 'config_filename': CONFIG_FILENAME,
        'plugin_directory': PLUGIN_DIRECTORY, 'same_machine_only': True,
        'writes_astrbot_install': False, 'requires_reload': True,
        'instructions': [
            '将完整插件放入 <AstrBot>/data/plugins/' + PLUGIN_DIRECTORY + '/，目录名保持不变。',
            '备份 <AstrBot>/data/config/' + CONFIG_FILENAME + '；首次安装可复制生成文件到该位置。已有绑定时只合并 bindings，避免覆盖其他鱼。',
            '在 AstrBot 面板的插件管理中重载爱之屋插件；不会自动重启机器人。',
            '在已登记会话发送 /lovehouse_status，确认有效绑定、插件待交和来源待补交。',
            '再发一轮有最终回复的测试对话，回爱之屋刷新确认完整对话增加；下一轮查询测试约定，核对最近返回的资料。配置生成不代表真实对话验收通过。']}}
