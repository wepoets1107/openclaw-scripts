#!/usr/bin/env python3
"""
Deribit DDH (Delta Dynamic Hedging)
每8小时检查，超出死区用永续合约配平

核心理解：
- delta_total（来自get_account_summary）= 目标净Delta，单位ETH，已含期权+永续
- ETH-PERPETUAL = 币本位永续（reversed），amount参数=合约数
- 1合约 ≈ 1/index_price ETH ≈ $1名义价值
- 对冲量 = int(|delta_total| × index_price) 合约

⚠️ 铁律（2026-05-14教训留存）：
- 单位搞错就亏损：币本位永续1合约=$1≠1 ETH，下错单损失几万
- 冷却30分 + MAX=5.0ETH/笔 是单批限额，超量分多笔执行（2026-05-15更新）
- 涉及下单操作先跟岛主确认，不擅自主张

⚠️ 铁律（2026-05-14反馈规则）：
- 每次执行完毕 → 必须输出完整pnl()数据面板，不许省略或只有一行总结
- print(pnl(...)) 不得被任何逻辑跳过，dry/force/cron 全场景均需输出
"""

import os, sys, json, time, requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
import threading

_script_dir = Path(__file__).parent.parent
if (_script_dir / ".env").exists(): load_dotenv(_script_dir / ".env")

DEAD = 5.0       # 死区(ETH)
GAP = 30         # 冷却间隔(分钟)
MAX = 5.0        # 单次最大对冲天(ETH)
ALERT = 50.0     # 总量告警(ETH)
CUR = "ETH"; HD = "ETH-PERPETUAL"
TNET = os.getenv("DDH_TESTNET","true").lower()=="true"
API = "https://test.deribit.com/api/v2" if TNET else "https://www.deribit.com/api/v2"
CID = os.getenv("DERIBIT_CLIENT_ID",""); CS = os.getenv("DERIBIT_CLIENT_SECRET","")
SF = _script_dir / "data" / "ddh-state.json"

def log(m):
    t = datetime.now(timezone(timedelta(hours=8))).strftime("%m-%d %H:%M:%S")
    print(f"[{t}] {m}", flush=True, file=sys.stderr)

class C:
    def __init__(self): self.t,self.e=None,0
    def r(self,m,p=None):
        h = {"Authorization":f"Bearer {self.t}"} if self.t else {}
        r = requests.post(API,json={"jsonrpc":"2.0","id":int(time.time()*1000)%1_000_000,"method":m,"params":p or {}},headers=h,timeout=15).json()
        if r.get("error"): raise Exception(f"{m}: [{r['error'].get('code','?')}] {r['error'].get('message','?')}")
        return r["result"]
    def a(self):
        if not self.t or time.time()>=self.e:
            r = self.r("public/auth",{"grant_type":"client_credentials","client_id":CID,"client_secret":CS})
            self.t,self.e = r["access_token"],time.time()+r["expires_in"]-60
    def ac(self):
        self.a(); return self.r("private/get_account_summary",{"currency":CUR})
    def po(self,k):
        self.a(); r = self.r("private/get_positions",{"currency":CUR,"kind":k})
        return r if isinstance(r,list) else []
    def px(self):
        return self.r("public/get_index_price",{"index_name":"eth_usd"}).get("index_price",0)
    def od(self,s,eth_amt,px):
        self.a()
        con=int(eth_amt*px)  # ETH→合约
        if con<1: return None
        r = self.r(f"private/{'buy' if s=='buy' else 'sell'}",{"instrument_name":HD,"amount":con,"type":"market"})
        o = r.get("order",r); return {"s":s,"eth":eth_amt,"con":con,"f":o.get("filled_amount",0),"a":o.get("average_price",0)}

def ep(ops):
    r=[]
    for p in ops:
        sz = float(p.get("size",0) or 0)
        if sz==0: continue
        n=p.get("instrument_name",""); ps=n.split("-")
        r.append({"e":ps[1] if len(ps)>=2 else "","k":int(ps[2]) if len(ps)>=4 and ps[2].isdigit() else 0,"ot":ps[3] if len(ps)>=4 else "?","sz":sz,"di":p.get("direction","buy"),
                  "d":float(p.get("delta",0)),"g":float(p.get("gamma",0)),"v":float(p.get("vega",0)),"t":float(p.get("theta",0))})
    return r

def pnl(ts,px,g0,pos,ppc,ppeth,act=None,nda=None):
    """面板 — 微信友好：表格简洁直观"""
    nd = g0["d"]
    nd_after = nda if nda is not None else nd
    L=[]
    L.append("="*36)
    L.append(f"🦐 DDH 数据面板  {ts}")
    L.append("="*36)
    L.append("")
    # 1) ETH价格 + Greeks表格
    L.append(f"| 项目 | 数值 |")
    L.append(f"|------|------|")
    L.append(f"| ETH 价格 | ${px:.0f} |")
    L.append(f"| **Net Delta** | **{nd:+.4f} ETH** {'✅ 死区内' if abs(nd)<=DEAD else '⚠️ 超死区'} |")
    L.append(f"| Gamma | {g0['g']:+.4f} |")
    L.append(f"| Vega | {g0['v']:+.2f} |")
    L.append(f"| Theta | {g0['t']:+.2f} |")
    if nda is not None and nda != nd:
        L.append(f"| After Delta | {nd_after:+.4f} ETH |")
    L.append("")
    # 2) 持仓
    L.append("**持仓：**")
    if pos:
        for d in pos:
            lbl="空" if d["di"]=="sell" else "多"
            L.append(f"- {lbl} {d['e']} {d['k']}{d['ot']} ×{int(abs(d['sz']))} — Δ{d['d']:+.2f}")
    pl="多头" if ppc>0 else ("空头" if ppc<0 else "无")
    L.append(f"- 永续 {HD}：{pl} {abs(ppc):,.0f}合约（≈{abs(ppeth):.2f} ETH）")
    L.append("")
    # 3) 结论
    L.append("**结论：**")
    if abs(nd_after)<=DEAD:
        L.append(f"Net Delta {nd_after:+.4f} ETH，在死区 ±{DEAD} ETH 范围内，无需对冲。静默。")
    else:
        L.append(f"Net Delta {nd_after:+.4f} ETH，超出死区 ±{DEAD} ETH，需对冲 {abs(nd_after):.4f} ETH ≈ {int(abs(nd_after)*px)} 合约。")
    if abs(nd)>ALERT:
        L.append(f"🚨 总敞口超上限 {ALERT} ETH！")
    if act:
        if act.get("dr"):
            L.append(f"[仿真] 拟{'做空' if act['s']=='sell' else '做多'} {act['eth']:.4f} ETH（{act['con']}合约）")
        else:
            lb="做空" if act["s"]=="sell" else "做多"; a=act.get("a",0) or 0
            L.append(f"[执行] {lb} {act['eth']:.4f} ETH @ ${a:.1f}（{act['con']}合约）")
    L.append("")
    L.append("="*36)
    L.append("=== 面板结束 ===")
    return "\n".join(L)

def main():
    dr="--dry" in sys.argv
    fc="--force" in sys.argv  # 岛主指令，跳过冷却和MAX
    ts=datetime.now(timezone(timedelta(hours=8))).strftime("%m-%d %H:%M")
    if not CID or not CS: return
    cl=C()
    try:
        px=cl.px(); log(f"ETH ${px:.2f}")
        ac=cl.ac()
        g={"d":ac.get("delta_total",0)or 0,"g":ac.get("options_gamma",0)or 0,
           "v":ac.get("options_vega",0)or 0,"t":ac.get("options_theta",0)or 0}
        pos=ep(cl.po("option"))
        sw=[p for p in cl.po("future") if "PERPETUAL" in p.get("instrument_name","")]

        # 永续持仓（合约数 + ETH实际值）
        ppc=sum(float(p.get("size",0)or 0) for p in sw)
        ppeth=sum(float(p.get("size_currency",0)or 0) for p in sw)

        nd=g["d"]  # delta_total IS net delta
        log(f"Net Delta={nd:+.4f} ETH  永续={ppeth:+.4f}ETH ({ppc:.0f}合约)")

        act,nda=None,None
        skp=False

        if abs(nd)>DEAD:
            # 冷却检查（--force跳过）
            if not fc and SF.exists():
                try:
                    st=json.loads(SF.read_text())
                    el=(time.time()-st.get("t",0))/60
                    if el<GAP:
                        log(f"冷却中({el:.0f}/{GAP}分)")
                        skp=True
                except: pass

        if abs(nd)>DEAD and not skp:
            # 分批对冲：超过MAX/笔则拆单，直到delta归零
            orders=[]
            cd=nd
            batch_max=MAX if not fc else 999

            while abs(cd)>DEAD*0.1:
                sd="sell" if cd>0 else "buy"  # 每轮根据实时delta方向定
                batch=min(abs(cd), batch_max)
                con=int(batch*px)
                if con<1:
                    log(f"末笔<1合约跳过({batch:.4f}ETH×${px:.0f}={con})")
                    break

                if dr:
                    orders.append({"dr":True,"s":sd,"eth":batch,"con":con})
                    cd+=batch if sd=="buy" else -batch
                else:
                    r=cl.od(sd,batch,px)
                    if r and r.get("f",0)>0:
                        r["s"]=sd; orders.append(r)
                        time.sleep(1)
                        ac2=cl.ac()
                        cd=ac2.get("delta_total",0)or 0
                        sw2=[p for p in cl.po("future") if "PERPETUAL" in p.get("instrument_name","")]
                        ppc=sum(float(p.get("size",0)or 0) for p in sw2)
                        ppeth=sum(float(p.get("size_currency",0)or 0) for p in sw2)
                        log(f"第{len(orders)}笔: {sd} {batch:.4f}ETH | delta残={cd:+.4f}")
                    else:
                        log(f"第{len(orders)+1}笔下单失败")
                        break

            if orders:
                nda=cd
                act=orders[-1]
                total_eth=sum(o.get("eth",0) or 0 for o in orders)
                log(f"分批对冲完成: {len(orders)}笔, 共约{total_eth:.4f}ETH")
                if not fc and not dr:
                    SF.parent.mkdir(parents=True,exist_ok=True)
                    SF.write_text(json.dumps({"t":time.time()}))

        # 每次执行都打印面板
        print(pnl(ts,px,g,pos,ppc,ppeth,act,nda))
        if not act:
            log(f"Net Delta {nd:+.4f} {'死区内' if abs(nd)<=DEAD else '超死区'}，静默")

    except Exception as e:
        log(f"异常: {e}")
        import traceback; traceback.print_exc(file=sys.stderr)

def main_ws():
    """WebSocket实时监控模式 — 常驻进程，秒级检测delta"""
    import websocket
    
    dr="--dry" in sys.argv
    fc="--force" in sys.argv
    
    if not CID or not CS:
        log("❌ 缺少API Key")
        return
    
    WS_URL = "wss://test.deribit.com/ws/api/v2" if TNET else "wss://www.deribit.com/ws/api/v2"
    cl = C()
    
    # 首次获取完整数据（用于面板）
    def refresh_snapshot():
        try:
            px = cl.px()
            ac = cl.ac()
            g = {"d":ac.get("delta_total",0)or 0,"g":ac.get("options_gamma",0)or 0,
                 "v":ac.get("options_vega",0)or 0,"t":ac.get("options_theta",0)or 0}
            pos = ep(cl.po("option"))
            sw = [p for p in cl.po("future") if "PERPETUAL" in p.get("instrument_name","")]
            ppc = sum(float(p.get("size",0)or 0) for p in sw)
            ppeth = sum(float(p.get("size_currency",0)or 0) for p in sw)
            return px, g, pos, ppc, ppeth
        except Exception as e:
            log(f"快照刷新异常: {e}")
            return None, None, None, None, None

    # 对冲执行（复用REST逻辑）
    def do_hedge(nd, px, g, pos, ppc, ppeth):
        orders = []
        cd = nd
        batch_max = MAX if not fc else 999
        ts = datetime.now(timezone(timedelta(hours=8))).strftime("%m-%d %H:%M")

        while abs(cd) > DEAD * 0.1:
            sd = "sell" if cd > 0 else "buy"
            batch = min(abs(cd), batch_max)
            con = int(batch * px)
            if con < 1:
                log(f"末笔<1合约跳过({batch:.4f}ETH×${px:.0f}={con})")
                break

            if dr:
                orders.append({"dr":True,"s":sd,"eth":batch,"con":con})
                cd += batch if sd == "buy" else -batch
            else:
                r = cl.od(sd, batch, px)
                if r and r.get("f",0) > 0:
                    r["s"] = sd; orders.append(r)
                    time.sleep(1)
                    ac2 = cl.ac()
                    cd = ac2.get("delta_total",0) or 0
                    sw2 = [p for p in cl.po("future") if "PERPETUAL" in p.get("instrument_name","")]
                    ppc = sum(float(p.get("size",0)or 0) for p in sw2)
                    ppeth = sum(float(p.get("size_currency",0)or 0) for p in sw2)
                    log(f"第{len(orders)}笔: {sd} {batch:.4f}ETH | delta残={cd:+.4f}")
                else:
                    log(f"第{len(orders)+1}笔下单失败")
                    break

        if orders:
            act = orders[-1]
            total_eth = sum(o.get("eth",0) or 0 for o in orders)
            log(f"分批对冲完成: {len(orders)}笔, 共约{total_eth:.4f}ETH")
            if not fc and not dr:
                SF.parent.mkdir(parents=True,exist_ok=True)
                SF.write_text(json.dumps({"t":time.time()}))
            # 刷新快照后打印面板
            snap = refresh_snapshot()
            if snap[0]:
                print(pnl(ts, snap[0], snap[1], snap[2], snap[3], snap[4], act, cd))
        else:
            print(pnl(ts, px, g, pos, ppc, ppeth, None, nd))

    # 初始快照
    snap = refresh_snapshot()
    if not snap[0]:
        log("❌ 初始快照失败，退出")
        return
    px, g, pos, ppc, ppeth = snap
    nd = g["d"]
    ts = datetime.now(timezone(timedelta(hours=8))).strftime("%m-%d %H:%M")
    print(pnl(ts, px, g, pos, ppc, ppeth))
    log(f"WS模式启动 | 初始delta={nd:+.4f} | 死区±{DEAD} | 每笔上限{MAX}ETH")

    # 如果初始delta已超死区，先对冲
    if abs(nd) > DEAD:
        log(f"初始delta超死区，立即对冲")
        do_hedge(nd, px, g, pos, ppc, ppeth)

    # WebSocket连接循环
    while True:
        try:
            ws = websocket.WebSocket()
            ws.connect(WS_URL, timeout=30)
            log(f"WS已连接 {WS_URL}")

            # 认证
            auth_req = json.dumps({"jsonrpc":"2.0","id":1,"method":"public/auth",
                "params":{"grant_type":"client_credentials","client_id":CID,"client_secret":CS}})
            ws.send(auth_req)
            auth_resp = json.loads(ws.recv())
            if auth_resp.get("error"):
                log(f"WS认证失败: {auth_resp['error']}")
                ws.close()
                time.sleep(10)
                continue
            log("WS认证成功")

            # 订阅portfolio
            sub_req = json.dumps({"jsonrpc":"2.0","id":2,"method":"private/subscribe",
                "params":{"channels":["user.portfolio.eth"]}})
            ws.send(sub_req)
            sub_resp = json.loads(ws.recv())
            log(f"WS订阅结果: {sub_resp.get('result','?')}")

            # 消息循环
            ws.settimeout(30)  # 30秒无消息则发ping
            while True:
                try:
                    msg = ws.recv()
                    if not msg:
                        break
                    data = json.loads(msg)
                    # 只处理portfolio推送
                    if data.get("params",{}).get("channel") == "user.portfolio.eth":
                        pdata = data["params"]["data"]
                        nd_new = pdata.get("delta_total", 0) or 0
                        px_new = pdata.get("index_price", 0) or px
                        # 更新greeks
                        g_new = {"d": nd_new,
                                 "g": pdata.get("options_gamma", 0) or 0,
                                 "v": pdata.get("options_vega", 0) or 0,
                                 "t": pdata.get("options_theta", 0) or 0}
                        
                        if abs(nd_new) > DEAD:
                            log(f"⚠️ delta={nd_new:+.4f} 超死区，触发对冲")
                            # 刷新完整快照后对冲
                            snap = refresh_snapshot()
                            if snap[0]:
                                do_hedge(snap[1]["d"], snap[0], snap[1], snap[2], snap[3], snap[4])
                            # 对冲后刷新面板
                            snap = refresh_snapshot()
                            if snap[0]:
                                px, g, pos, ppc, ppeth = snap
                                ts = datetime.now(timezone(timedelta(hours=8))).strftime("%m-%d %H:%M")
                                print(pnl(ts, px, g, pos, ppc, ppeth))
                        else:
                            # 更新缓存数据
                            px = px_new
                            g = g_new
                except websocket.WebSocketTimeoutException:
                    # 发ping保活
                    try:
                        ws.ping()
                    except:
                        break
                except json.JSONDecodeError:
                    continue

        except Exception as e:
            log(f"WS异常: {e}，10秒后重连")
            time.sleep(10)
            continue


if __name__=="__main__":
    if "--ws" in sys.argv:
        main_ws()
    else:
        main()