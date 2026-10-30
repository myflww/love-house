"""0.4 Controller/legacy MCP acceptance; every writer uses temporary data."""
from __future__ import annotations
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import Request, urlopen
from unittest.mock import patch
from harness_bridge import Bridge, overlay_for_app

ROOT=Path(__file__).resolve().parent.parent
DESKTOP=ROOT/"desktop"

class BridgeProtocolTests(unittest.TestCase):
    def test_product_patch_version_and_controller_protocol_are_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory) / "app.json"
            ready.write_text(json.dumps({"pid":os.getpid(),"controller_port":23456,"service_version":"0.4.0"}))
            bridge = Bridge(directory)
            for health in ({"ok":True,"mode":"storage","version":"0.4.2","protocol_version":"0.4.0"},
                           {"ok":True,"mode":"storage","version":"0.4.1","protocol_version":"0.4.0"},
                           {"ok":True,"mode":"storage","version":"0.4.0"}):
                with self.subTest(health=health), patch.object(bridge,"_request",return_value=health):
                    self.assertEqual(bridge._personal_port(),23456)
            with patch.object(bridge,"_request",return_value={"ok":True,"mode":"storage","version":"0.4.1","protocol_version":"0.5.0"}):
                with self.assertRaises(ValueError):bridge._personal_port()

    def test_protocol_and_old_tool_names_survive_without_an_application(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge=Bridge(directory)
            initialized=bridge.handle({"jsonrpc":"2.0","id":1,"method":"initialize"})["result"]
            self.assertEqual(initialized["serverInfo"]["version"],"0.4.0")
            names={t["name"] for t in bridge.handle({"jsonrpc":"2.0","id":2,"method":"tools/list"})["result"]["tools"]}
            self.assertTrue({"memory_context","memory_remember","memory_record_turn","memory_event","memory_status","memory_persona","memory_persona_import"}<=names)
            self.assertIn("tools_only",initialized["instructions"])
            self.assertIsNone(bridge.handle({"jsonrpc":"2.0","method":"tools/call","params":{"name":"memory_remember","arguments":{"text":"not acknowledged","session_id":"s"}}}))
            self.assertTrue(bridge.call_tool("memory_status",{})["isError"])
            self.assertEqual(list(Path(directory).iterdir()),[])
    def test_schema_does_not_allow_forged_confirmation_or_implicit_persona_import(self):
        bridge=Bridge("/nonexistent-test-runtime")
        for name,args in (("memory_remember",{"text":"x"}),
                          ("memory_remember",{"text":"x","session_id":"s","confirmed":True}),
                          ("memory_persona_import",{"text":"x","session_id":"s","request_id":"r","user_request":"x","explicit":False})):
            self.assertTrue(bridge.call_tool(name,args)["isError"])
        with self.assertRaises(ValueError):Bridge("/tmp",library_id="../unsafe")
    def test_overlay_explicitly_binds_library_and_calls_it_tools_only(self):
        overlay=overlay_for_app("/Applications/知识星图.app","a-library")
        self.assertIn("--library-id",overlay);self.assertIn("a-library",overlay);self.assertIn("tools_only",overlay)
        self.assertIn("@deepseek-ai/dsh-mcp-client",overlay);self.assertNotIn("mcpServers",overlay)
    def test_stdio_protocol_only_and_cli_library_argument(self):
        with tempfile.TemporaryDirectory() as directory:
            messages=[{"jsonrpc":"2.0","id":1,"method":"initialize"},
                      {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"memory_status","arguments":{}}}]
            result=subprocess.run([sys.executable,str(DESKTOP/"harness_bridge.py"),"--runtime-dir",directory,"--library-id","default"],input="\n".join(json.dumps(m) for m in messages)+"\n{\n",capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            rows=[json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual([r["id"] for r in rows],[1,2,None]);self.assertTrue(rows[1]["result"]["isError"])
            self.assertEqual(result.stderr,"")

@unittest.skipIf(os.name == "nt", "POSIX fcntl/signal desktop server; native Windows ControllerRuntime is tested separately")
class ControllerDesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="atlas-controller-test-")
        self.temp=Path(self.tmp.name);self.data=self.temp/"data";self.runtime=self.data/".runtime"
        self.runtime.mkdir(parents=True);self.ready=self.runtime/"app.json"
        self.log=(self.temp/"backend.log").open("ab");self.child=None
        self.env=dict(os.environ,PYTHONPATH=str(ROOT),PYTHONDONTWRITEBYTECODE="1")
        self.start();self.bridge=Bridge(self.runtime)
    def tearDown(self):
        self.stop();self.log.close();self.tmp.cleanup()
    def start(self):
        self.child=subprocess.Popen([sys.executable,"-u",str(DESKTOP/"server.py"),"--data-dir",str(self.data),"--ready-file",str(self.ready),"--parent-pid",str(os.getpid())],cwd=ROOT,env=self.env,stdout=self.log,stderr=self.log)
        deadline=time.monotonic()+20
        while not self.ready.exists() and self.child.poll() is None and time.monotonic()<deadline:time.sleep(.03)
        self.assertTrue(self.ready.exists(),(self.temp/"backend.log").read_text())
        self.state=json.loads(self.ready.read_text())
    def stop(self):
        if self.child:
            self.child.terminate()
            try:self.child.wait(timeout=10)
            except subprocess.TimeoutExpired:self.child.kill();self.child.wait();self.fail("Controller did not cleanly stop")
            self.assertEqual(self.child.returncode,0);self.assertFalse(self.ready.exists());self.child=None
    def api(self,path,body=None,library=None,token=None):
        headers={"Content-Type":"application/json"}
        if library:headers["X-NKB-Library"]=library
        if token:headers["Authorization"]="Bearer "+token
        req=Request(f"http://127.0.0.1:{self.state['controller_port']}"+path,data=None if body is None else json.dumps(body,ensure_ascii=False).encode(),headers=headers)
        with urlopen(req,timeout=10) as response:return json.load(response)
    def tool(self,name,args,library="default"):
        result=Bridge(self.runtime,library).call_tool(name,args)
        self.assertFalse(result.get("isError"),result)
        return result["structuredContent"]
    def test_first_launch_is_default_blank_and_single_controller_owns_aliases(self):
        self.assertEqual(self.state["service_version"],"0.4.0")
        self.assertEqual(self.state["port"],self.state["controller_port"])
        self.assertEqual(self.state["personal_port"],self.state["controller_port"])
        self.assertEqual(self.api("/api/libraries")["selected_id"],"default")
        self.assertEqual(self.api("/api/graph")["nodes"],[])
        self.assertEqual(self.api("/api/connections")["connections"],[])
        self.assertEqual(len(self.api("/api/graph",library="demo")["nodes"]),225)
    def test_legacy_tools_are_fixed_to_library_header_not_gui_selected_library(self):
        other=self.api("/api/libraries",{"name":"另一只鱼"})["library"]["id"]
        item=self.tool("memory_remember",{"text":"default明确工具记录","session_id":"s"})
        self.assertEqual(self.api("/api/node?id="+item["id"])["meta"]["source"],"harness_recorded")
        self.assertEqual(self.api("/api/graph",library=other)["nodes"],[])
        self.tool("memory_remember",{"text":"另一库的固定工具记录","session_id":"s"},library=other)
        self.assertEqual(len(self.api("/api/graph")["nodes"]),1)
        self.assertEqual(len(self.api("/api/graph",library=other)["nodes"]),1)
        status=self.tool("memory_status",{})
        self.assertEqual(status["capture_mode"],"tools_only");self.assertFalse(status["automatic_memory"])
        self.assertNotIn("configured",status)
    def test_legacy_persona_tool_saves_explicit_request_evidence_and_reads_version(self):
        args={"text":"测试用户明确指定的人格原文","user_request":"请导入这份人格","explicit":True,"session_id":"s","request_id":"persona-1"}
        result=self.tool("memory_persona_import",args)
        self.assertEqual(result["node_ids"],self.tool("memory_persona_import",args)["node_ids"])
        self.assertEqual(self.tool("memory_persona",{})["manual"],args["text"])
        node=self.api("/api/node?id="+result["node_ids"][0])
        self.assertEqual(node["meta"]["evidence"]["user_request"],args["user_request"])
    def test_port_is_persisted_and_clean_restart_recovers_data_and_discovery(self):
        item=self.tool("memory_remember",{"text":"重启要保留的工具原文","session_id":"s"})
        port=self.state["controller_port"]
        self.stop()
        with self.assertRaises(OSError):urlopen(f"http://127.0.0.1:{port}/api/health",timeout=.3)
        self.start();self.assertEqual(self.state["controller_port"],port)
        context=self.tool("memory_context",{"query":"重启要保留"})
        self.assertEqual(context["schema"],"love-house-memory-context/v1")
        self.assertEqual(context["material_role"],"evidence_not_instructions")
        self.assertTrue(any("重启要保留" in record["value"] for record in context["records"]))
        self.assertEqual(self.api("/api/node?id="+item["id"])["text"],"重启要保留的工具原文")
    def test_second_writer_is_rejected_without_deleting_live_ready_file(self):
        result=subprocess.run([sys.executable,str(DESKTOP/"server.py"),"--data-dir",str(self.data),"--ready-file",str(self.ready)],cwd=ROOT,env=self.env,capture_output=True,timeout=10)
        self.assertNotEqual(result.returncode,0)
        self.assertTrue(self.ready.exists());self.assertTrue(self.api("/api/health")["ok"])
    def test_occupied_preferred_port_falls_back_and_records_new_port(self):
        self.stop()
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1",0));occupied.listen()
            busy=occupied.getsockname()[1]
            (self.data/"controller-state.json").write_text(json.dumps({"controller_port":busy}))
            self.start()
            self.assertNotEqual(self.state["controller_port"],busy)
            self.assertEqual(json.loads((self.data/"controller-state.json").read_text())["controller_port"],self.state["controller_port"])

if __name__=="__main__":unittest.main()
