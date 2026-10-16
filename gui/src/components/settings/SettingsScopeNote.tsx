const notes: Record<string,string> = {
 appearance:'本机界面 · 修改后即时生效', accounts:'本机保存 · 保存后用于后续请求；正在进行的请求保持原配置',
 behavior:'本机偏好 · 后续操作生效；会话权限按当前对话设置', perms:'当前对话 · 权限切换即时生效；已记住的授权可在下方撤销',
 rewind:'恢复方式：本机偏好，下次回溯生效。清理设置：保存到后端，后续清理生效。',
 remote:'本机连接 · 手机消息进入当前远程会话', archive:'本机对话列表 · 恢复后返回侧栏', pet:'本机桌宠 · 修改后即时生效',
};
export function SettingsScopeNote({tab}:{tab:string}) { return <p className="xy-settings-scope">{notes[tab]}</p>; }
