package io.github.myflww.lovehouse.upgradeqa;

import android.app.*;
import android.content.*;
import android.content.pm.*;
import android.database.Cursor;
import android.net.Uri;
import android.os.*;
import android.webkit.WebView;
import java.io.*;
import java.net.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;
import org.json.*;

/** QA only; targets the unmodified original-signed release process, using only
 * owned synthetic emulator data. No cookies, keys or memory are emitted. */
public final class UpgradeProbeInstrumentation extends Instrumentation {
 static final String APP="io.github.myflww.lovehouse.preview";
 static final String CERT="ca4b184194816fe3617feaa841e11b47f5a9a9a00493e8cbc015210c04a3a4cc";
 static final String[] NAMES={"升级验收小屋A0106","升级验收小屋B0106"};
 static final String[] TEXTS={"升级前原话A：海边🙂；Unicode e\u0301 / é；完整保留。","升级前原话B：独立小屋❤️；不能与A混合。"};
 static final String[] REPLIES={"升级前回复A：记得约定。","升级前回复B：保持独立。"};
 static final String ACCOUNT="cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
 static final String SYNTHETIC="SYNTHETIC_ONLY_ANDROID_0106_PERSISTENCE";
 static final Uri DOCUMENT=Uri.parse("content://io.github.myflww.lovehouse.preview.test.synthetic-saf/document/export.json");
 volatile String stage="arguments";volatile boolean finished;String mode,url,cookie; Activity activity; Bundle args;
 @Override public void onCreate(Bundle value){super.onCreate(value);args=value==null?new Bundle():new Bundle(value);start();}
 @Override public void onStart(){
  Bundle report=new Bundle();mode=args.getString("mode","");report.putString("mode",mode);
  report.putString("protocol","love-house-original-upgrade-0106/v1");
  Thread progress=new Thread(()->{String previous="";while(!finished){String current=stage;if(!current.equals(previous)){Bundle safe=new Bundle();safe.putString("qa_stage",current);safe.putString("mode",mode);try{sendStatus(2,safe);}catch(Throwable ignored){return;}previous=current;}SystemClock.sleep(100);}},"owned-qa-stage");progress.setDaemon(true);progress.start();
  try{
   checkIdentity(mode.equals("seed"));
   if(mode.equals("seed")){legacy();seed();checkLegacy();}
   else if(mode.equals("verify")){legacy();checkLegacy();}
   else if(mode.equals("migrate"))migrate();
   else if(mode.equals("persisted"))persisted();
   else if(mode.equals("credential_seed"))credential(true);
   else if(mode.equals("credential_delete"))credential(false);
   else throw new AssertionError();
   report.putBoolean("ok",true);report.putInt("api_level",Build.VERSION.SDK_INT);
   report.putBoolean("original_certificate",true);report.putInt("version_code",mode.equals("seed")?3:4);
   report.putInt("model_calls",0);finish(Activity.RESULT_OK,report);
  }catch(Throwable failure){report.putBoolean("ok",false);report.putString("error_stage",stage);
   report.putString("exception",failure.getClass().getSimpleName());finish(1,report);}finally{finished=true;}
 }
 void checkIdentity(boolean old)throws Exception{
  stage="disposable_identity";java.lang.Process p=new ProcessBuilder("/system/bin/getprop","ro.kernel.qemu").start();
  require(read(p.getInputStream()).trim().equals("1")&&p.waitFor()==0);require(Build.VERSION.SDK_INT==28||Build.VERSION.SDK_INT==36);
  PackageInfo info=getTargetContext().getPackageManager().getPackageInfo(APP,PackageManager.GET_SIGNING_CERTIFICATES);
  require(info.versionCode==(old?3:4));require((old?"0.8.0rc2":"0.10.6rc1").equals(info.versionName));
  Signature[] signatures=info.signingInfo.getApkContentsSigners();require(signatures.length==1);
  StringBuilder hex=new StringBuilder();for(byte b:MessageDigest.getInstance("SHA-256").digest(signatures[0].toByteArray()))hex.append(String.format(Locale.ROOT,"%02x",b&255));
  require(CERT.equals(hex.toString()));
 }
 Activity launch(String className)throws Exception{
  Intent i=new Intent().setClassName(APP,"io.github.myflww.lovehouse."+className).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK).putExtra("legacy",true);
  ActivityMonitor monitor=addMonitor("io.github.myflww.lovehouse."+className,null,false);
  try{onMain(()->getTargetContext().startActivity(i));Activity result=waitForMonitorWithTimeout(monitor,30000);require(result!=null);return result;}finally{removeMonitor(monitor);}
 }
 void onMain(Runnable action)throws Exception{
  CountDownLatch done=new CountDownLatch(1);AtomicReference<Throwable> failure=new AtomicReference<>();
  new Handler(Looper.getMainLooper()).post(()->{try{action.run();}catch(Throwable e){failure.set(e);}finally{done.countDown();}});
  require(done.await(30,TimeUnit.SECONDS)&&failure.get()==null);
 }
 void legacy()throws Exception{stage="legacy_ready";activity=launch("MainActivity");waitJs("document.documentElement.dataset.appReady==='true' && window.LoveHouseApp && !document.getElementById('newMemory').disabled");}
 Object call(Activity target,String name)throws Exception{Method m=target.getClass().getDeclaredMethod(name);m.setAccessible(true);return m.invoke(target);}
 Object js(String body)throws Exception{
  CountDownLatch done=new CountDownLatch(1);AtomicReference<String> value=new AtomicReference<>();AtomicReference<Throwable> error=new AtomicReference<>();
  onMain(()->{try{WebView web=(WebView)call(activity,"webViewForTest");require(web!=null);web.evaluateJavascript("(function(){"+body+"})()",result->{value.set(result);done.countDown();});}catch(Throwable e){error.set(e);done.countDown();}});
  require(done.await(30,TimeUnit.SECONDS)&&error.get()==null&&value.get()!=null);return new JSONTokener(value.get()).nextValue();
 }
 void exec(String body)throws Exception{js(body+";return true;");}
 void waitJs(String expression)throws Exception{long end=SystemClock.uptimeMillis()+90000;do{if(Boolean.TRUE.equals(js("return Boolean("+expression+");")))return;SystemClock.sleep(100);}while(SystemClock.uptimeMillis()<end);throw new AssertionError();}
 void seed()throws Exception{
  for(int n=0;n<2;n++){
   stage="seed_library_"+n;exec("document.getElementById('newLibrary').click();document.getElementById('libraryName').value="+JSONObject.quote(NAMES[n])+";document.getElementById('libraryForm').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));");
   waitJs("!document.getElementById('libraryDialog').open && document.getElementById('librarySelect').selectedOptions[0].textContent==="+JSONObject.quote(NAMES[n]));
   stage="seed_editor_open_"+n;exec("document.getElementById('newMemory').click();");waitJs("document.getElementById('memoryDialog').open && !document.getElementById('saveMemory').disabled");
   stage="seed_editor_fill_"+n;exec("document.getElementById('memoryTitle').value='UPGRADE_0106_"+n+"';document.getElementById('memoryText').value="+JSONObject.quote(TEXTS[n])+";document.getElementById('memoryAssistant').value="+JSONObject.quote(REPLIES[n])+";document.getElementById('memoryTags').value='升级验收,独立库"+n+"';");
   stage="seed_editor_submit_"+n;exec("document.getElementById('memoryForm').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));");
   stage="seed_editor_saved_"+n;
   waitJs("!document.getElementById('memoryDialog').open && document.querySelectorAll('.memory-card').length===1");
  }
 }
 void selectLegacy(int n)throws Exception{
  exec("var s=document.getElementById('librarySelect');var o=Array.from(s.options).find(function(x){return x.textContent==="+JSONObject.quote(NAMES[n])+";});if(!o)throw Error('missing synthetic library');s.value=o.value;s.dispatchEvent(new Event('change',{bubbles:true}));");
  waitJs("!document.getElementById('librarySelect').disabled && document.getElementById('librarySelect').selectedOptions[0].textContent==="+JSONObject.quote(NAMES[n])+" && document.querySelectorAll('.memory-card').length===1");
 }
 void checkLegacy()throws Exception{
  for(int n=0;n<2;n++){
   stage="check_legacy_"+n;selectLegacy(n);
   exec("window.__qaExport=null;window.LoveHouseApp.store.exportLibrary(document.getElementById('librarySelect').value).then(function(x){window.__qaExport=x;});");waitJs("window.__qaExport!==null");
   JSONObject exported=new JSONObject(String.valueOf(js("return JSON.stringify(window.__qaExport);")));require(NAMES[n].equals(exported.getString("name")));
   JSONObject nodes=exported.getJSONObject("memory").getJSONObject("nodes");require(nodes.length()==1);JSONObject row=nodes.getJSONObject(nodes.keys().next());
   require(TEXTS[n].equals(row.getString("text"))&&REPLIES[n].equals(row.getJSONObject("meta").getString("assistant_reply")));
   require(row.toString().contains("升级验收")&&row.toString().contains("独立库"+n)&&!row.toString().contains(TEXTS[1-n]));
   require(row.getString("label").equals("UPGRADE_0106_"+n));
   JSONArray tags=row.getJSONArray("tags");require(tags.length()==2);
   Set<String> actual=new HashSet<>();for(int t=0;t<tags.length();t++)actual.add(tags.getString(t));
   require(actual.equals(new HashSet<>(Arrays.asList("升级验收","独立库"+n))));
  }
 }
 void engine(Activity target)throws Exception{
  stage="engine_bootstrap";activity=target;long end=SystemClock.uptimeMillis()+120000;
  do{AtomicReference<String> value=new AtomicReference<>();onMain(()->{try{value.set((String)call(activity,"engineUrlForTest"));cookie=(String)call(activity,"engineManagementCookieForTest");}catch(Exception ignored){}});url=value.get();if(url!=null&&cookie!=null)break;SystemClock.sleep(100);}while(SystemClock.uptimeMillis()<end);
  require(url!=null&&cookie!=null);waitJs("typeof S!=='undefined' && S.mode==='serve' && !!window.LoveHousePortability && !!window.LoveHouseEngineFiles");request("/api/updates/settings",new JSONObject().put("auto_check",false),null);
 }
 void migrateOnce()throws Exception{
  stage="explicit_migration_button";selectLegacy(0);ActivityMonitor monitor=addMonitor("io.github.myflww.lovehouse.EngineActivity",null,false);
  try{exec("window.confirm=function(){return true;};document.getElementById('migrateLegacy').click();");Activity opened=waitForMonitorWithTimeout(monitor,30000);require(opened!=null);engine(opened);}finally{removeMonitor(monitor);}
 }
 int matching(JSONArray nodes,int index)throws Exception{
  int count=0;
  for(int n=0;n<nodes.length();n++){
   JSONObject row=nodes.getJSONObject(n);
   require(!TEXTS[1].equals(row.optString("text")));
   if(TEXTS[index].equals(row.optString("text"))){
    count++;require(REPLIES[index].equals(row.getJSONObject("meta").getString("assistant_reply")));
    require(row.getString("label").equals("UPGRADE_0106_"+index));JSONArray tags=row.getJSONArray("tags");
    Set<String> values=new HashSet<>();for(int t=0;t<tags.length();t++)values.add(tags.getString(t));
    require(tags.length()==2&&values.equals(new HashSet<>(Arrays.asList("升级验收","独立库"+index))));
   }
  }
  return count;
 }
 void checkShare(String content)throws Exception{
  JSONObject share=new JSONObject(content);require(share.getString("format").equals("love-house-memory-share/v1"));
  JSONObject map=share.getJSONObject("memory").getJSONObject("nodes");JSONArray rows=new JSONArray();
  Iterator<String> keys=map.keys();while(keys.hasNext())rows.put(map.getJSONObject(keys.next()));
  require(rows.length()==1&&matching(rows,0)==1);
 }
 String migratedLibrary()throws Exception{
  JSONArray libraries=request("/api/libraries",null,null).getJSONArray("libraries");String id=null;int count=0;
  for(int n=0;n<libraries.length();n++){JSONObject lib=libraries.getJSONObject(n);JSONArray nodes=request("/api/graph",null,lib.getString("id")).getJSONArray("nodes");int found=matching(nodes,0);require(found<=1);if(found==1){count++;id=lib.getString("id");require(nodes.length()==1);}}
  require(count==1&&id!=null);return id;
 }
 void migrate()throws Exception{
  legacy();Activity originalLegacy=activity;checkLegacy();migrateOnce();stage="migration_scoped";String id=migratedLibrary();int count=request("/api/libraries",null,null).getJSONArray("libraries").length();
  stage="return_to_original_legacy";onMain(activity::finish);activity=originalLegacy;
  long resumeDeadline=SystemClock.uptimeMillis()+30000;boolean resumed=false;
  do{AtomicReference<Boolean> visible=new AtomicReference<>(false);onMain(()->visible.set(!activity.isFinishing()&&!activity.isDestroyed()&&activity.hasWindowFocus()));if(visible.get()){resumed=true;break;}SystemClock.sleep(100);}while(SystemClock.uptimeMillis()<resumeDeadline);require(resumed);
  waitJs("document.documentElement.dataset.appReady==='true' && !document.getElementById('librarySelect').disabled");
  checkLegacy();migrateOnce();stage="migration_duplicate";require(id.equals(migratedLibrary())&&count==request("/api/libraries",null,null).getJSONArray("libraries").length());
  stage="engine_backup";request("/api/library/select",new JSONObject().put("library_id",id),null);
  exec("selectMemoryLibrary("+JSONObject.quote(id)+");");waitJs("S.libraryId==="+JSONObject.quote(id)+" && !S.libraryChanging && !MEMORY.busy && !writeBusy");
  JSONObject preview=request("/api/sharing/preview",new JSONObject(),id);
  JSONObject exported=request("/api/sharing/download",new JSONObject().put("format","json").put("confirm",true).put("expected_revision",preview.getString("content_revision")),id);
  String content=exported.getString("content");checkShare(content);content=nativeSave();
  stage="engine_restore";JSONObject restored=request("/api/sharing/import",new JSONObject().put("confirm",true).put("content",content).put("name","升级验收恢复0106"),null);
  String restoredId=restored.getJSONObject("library").getString("id");require(!id.equals(restoredId));JSONArray restoredNodes=request("/api/graph",null,restoredId).getJSONArray("nodes");require(restoredNodes.length()==1&&matching(restoredNodes,0)==1);
  require(!request("/api/organizer",null,restoredId).getJSONObject("configuration").getBoolean("configured"));
  getTargetContext().getSharedPreferences("0106-owned-qa",Context.MODE_PRIVATE).edit().putString("migrated",id).putString("restored",restoredId).putInt("library_count",count+1).commit();
 }
 String nativeSave()throws Exception{
  stage="engine_saf_save";ContentResolver resolver=getTargetContext().getContentResolver();resolver.delete(DOCUMENT,null,null);
  IntentFilter filter=new IntentFilter(Intent.ACTION_CREATE_DOCUMENT);filter.addCategory(Intent.CATEGORY_OPENABLE);filter.addDataType("application/json");
  ActivityMonitor monitor=addMonitor(filter,new ActivityResult(Activity.RESULT_OK,new Intent().setData(DOCUMENT)),true);
  try{
   exec("window.__qaSaved=null;window.addEventListener('lovehouse-file-saved',function(e){window.__qaSaved=e.detail;});window.LoveHousePortability.openShare();");
   waitJs("document.getElementById('memoryShareDialog').open && !document.getElementById('sharePersonalConsent').disabled");
   exec("document.getElementById('sharePersonalConsent').checked=true;document.getElementById('sharePersonalConsent').dispatchEvent(new Event('change')); ");
   waitJs("!document.getElementById('downloadMemoryJSON').disabled");exec("document.getElementById('downloadMemoryJSON').click();");
   long end=SystemClock.uptimeMillis()+30000;while(monitor.getHits()!=1&&SystemClock.uptimeMillis()<end)SystemClock.sleep(100);require(monitor.getHits()==1);
   end=SystemClock.uptimeMillis()+30000;boolean opened=false;
   do{try(Cursor c=resolver.query(DOCUMENT,null,null,null,null)){require(c!=null&&c.moveToFirst());if(c.getInt(c.getColumnIndexOrThrow("open_count"))==1){opened=true;break;}}SystemClock.sleep(100);}while(SystemClock.uptimeMillis()<end);require(opened);
   ContentValues allow=new ContentValues();allow.put("allow_read",true);resolver.update(DOCUMENT,allow,null,null);String payload=null;end=SystemClock.uptimeMillis()+30000;
   do{try(Cursor c=resolver.query(DOCUMENT,null,null,null,null)){require(c!=null&&c.moveToFirst());if(c.getInt(c.getColumnIndexOrThrow("closed"))==1){require(c.getString(c.getColumnIndexOrThrow("error")).equals(""));payload=c.getString(c.getColumnIndexOrThrow("payload"));break;}}SystemClock.sleep(100);}while(SystemClock.uptimeMillis()<end);
   require(payload!=null);checkShare(payload);
   waitJs("window.__qaSaved && window.__qaSaved.saved===true && window.__qaSaved.cancelled===false");
   return payload;
  }finally{removeMonitor(monitor);ContentValues allow=new ContentValues();allow.put("allow_read",true);try{resolver.update(DOCUMENT,allow,null,null);}catch(Exception ignored){}}
 }
 void persisted()throws Exception{
  legacy();checkLegacy();engine(launch("EngineActivity"));stage="engine_after_process_restart";android.content.SharedPreferences p=getTargetContext().getSharedPreferences("0106-owned-qa",Context.MODE_PRIVATE);
  String id=p.getString("migrated",null),restored=p.getString("restored",null);require(id!=null&&restored!=null&&!id.equals(restored));require(p.getInt("library_count",-1)==request("/api/libraries",null,null).getJSONArray("libraries").length());
  for(String each:new String[]{id,restored}){JSONArray nodes=request("/api/graph",null,each).getJSONArray("nodes");require(nodes.length()==1&&matching(nodes,0)==1);}
 }
 void credential(boolean seed)throws Exception{
  stage=seed?"keystore_seed":"keystore_after_process_restart_delete";Class<?> type=getTargetContext().getClassLoader().loadClass("io.github.myflww.lovehouse.AndroidCredentialVault");Constructor<?> constructor=type.getDeclaredConstructor(Context.class);constructor.setAccessible(true);Object vault=constructor.newInstance(getTargetContext());
  Method method=type.getDeclaredMethod("call",String.class,String.class,String.class);method.setAccessible(true);
  if(seed)require(new JSONObject((String)method.invoke(vault,"set",ACCOUNT,SYNTHETIC)).getBoolean("ok"));
  else{JSONObject value=new JSONObject((String)method.invoke(vault,"get",ACCOUNT,null));require(value.getBoolean("ok")&&value.getString("value").equals(SYNTHETIC));require(new JSONObject((String)method.invoke(vault,"delete",ACCOUNT,null)).getBoolean("ok"));require(new JSONObject((String)method.invoke(vault,"get",ACCOUNT,null)).getString("value").equals(""));}
 }
 JSONObject request(String path,JSONObject body,String library)throws Exception{
  HttpURLConnection c=(HttpURLConnection)new URL(url+path.substring(1)).openConnection();c.setConnectTimeout(10000);c.setReadTimeout(30000);c.setRequestProperty("Cookie",cookie);if(library!=null)c.setRequestProperty("X-NKB-Library",library);
  if(body!=null){c.setRequestMethod("POST");c.setDoOutput(true);c.setRequestProperty("Content-Type","application/json");try(OutputStream out=c.getOutputStream()){out.write(body.toString().getBytes(StandardCharsets.UTF_8));}}
  try{require(c.getResponseCode()==200);return new JSONObject(read(c.getInputStream()));}finally{c.disconnect();}
 }
 static String read(InputStream input)throws Exception{try(InputStream in=input;ByteArrayOutputStream out=new ByteArrayOutputStream()){byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1){require(out.size()+n<8*1024*1024);out.write(b,0,n);}return out.toString("UTF-8");}}
 static void require(boolean value){if(!value)throw new AssertionError();}
}
