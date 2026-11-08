(function () {
  'use strict';
  document.documentElement.dataset.lovehousePlatform = 'android';
  var gesture = document.getElementById('canvasHelp');
  function touchHint() {
    var text = '单指拖动 · ＋ / － 缩放 · 轻点节点';
    if (gesture && gesture.textContent !== text) gesture.textContent = text;
  }
  if (gesture) { touchHint(); new MutationObserver(touchHint).observe(gesture, {childList: true}); }
  var canvas = document.getElementById('cv');
  if (canvas) canvas.setAttribute('aria-label', '记忆星图：单指拖动、用加减按钮缩放，轻点节点查看原文，也可使用记忆列表。');
  var bar = document.createElement('div');
  bar.id = 'androidMemoryBar';
  var note = document.createElement('span');
  note.textContent = '本机完整记忆 · 0.10.6rc1';
  var help = document.createElement('button');
  help.type = 'button'; help.textContent = '手机接入说明';
  var back = document.createElement('button');
  back.type = 'button'; back.textContent = '旧版离线库';
  back.title = '返回原有离线记忆；可将旧库迁移到完整记忆引擎';
  back.addEventListener('click', function () { if (window.LoveHouseEngineFiles) window.LoveHouseEngineFiles.closeEngine(); });
  var dialog = document.createElement('dialog');
  var heading = document.createElement('h2'); heading.textContent = '手机里的爱之屋';
  var body = document.createElement('p');
  body.textContent = '记忆、人格、整理和召回使用与桌面相同的引擎，保存在本机。请在“整理”中为当前记忆库配置模型 API；费用由所选模型服务收取。';
  var scope = document.createElement('p');
  scope.textContent = '复制连接配置要交给实际运行 Agent 的宿主。127.0.0.1 只指这台手机：电脑或云服务器上的 Agent 请连接它所在设备的爱之屋服务，再在手机查看那台服务。手机不会读取 QQ 或其他 App；自动采集依赖 Agent 宿主上报。';
  var background = document.createElement('p');
  background.textContent = '手机进程存活时可接收已配置 Agent 的上报；系统省电或结束进程可能停止接收，关闭界面后不保证持续运行。需要全天候记录的鱼，建议在电脑或服务器持续运行爱之屋。再次打开会恢复本机记忆；同一记忆库的连接配置继续有效。';
  var close = document.createElement('button'); close.type = 'button'; close.textContent = '知道了';
  close.addEventListener('click', function () { dialog.close(); });
  dialog.append(heading, body, scope, background, close);
  help.addEventListener('click', function () { dialog.showModal(); });
  window.LoveHouseAndroidHelp = function () { if (!dialog.open) dialog.showModal(); };
  bar.append(note, help, back);
  document.body.append(bar, dialog);
}());
