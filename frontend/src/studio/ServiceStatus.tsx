import {useCallback, useEffect, useRef, useState} from "react";
import {studio} from "./client";
import {Icon} from "./icons";
import {Modal} from "./Modal";
import type {StudioHealth} from "./types";

export function useStudioHealth() {
  const [health, setHealth] = useState<StudioHealth | null>(null);
  const [connection, setConnection] = useState<"checking" | "online" | "offline">("checking");
  const [checking, setChecking] = useState(false);
  const active = useRef(false);
  const request = useRef<Promise<StudioHealth | null> | null>(null);
  const refresh = useCallback((recheck = false): Promise<StudioHealth | null> => {
    if (request.current) return request.current;
    if (active.current) setChecking(true);
    request.current = (recheck ? studio.recheckService().then(() => studio.health()) : studio.health()).then(value => {
      if (active.current) {setHealth(value); setConnection("online");}
      return value;
    }).catch(() => {
      if (active.current) {setHealth(null); setConnection("offline");}
      return null;
    }).finally(() => {request.current = null; if (active.current) setChecking(false);});
    return request.current;
  }, []);
  useEffect(() => {
    active.current = true;
    void refresh();
    const checkVisible = () => {if (document.visibilityState === "visible") void refresh();};
    const timer = window.setInterval(checkVisible, 15000);
    window.addEventListener("focus", checkVisible);
    document.addEventListener("visibilitychange", checkVisible);
    return () => {active.current = false; window.clearInterval(timer); window.removeEventListener("focus", checkVisible); document.removeEventListener("visibilitychange", checkVisible);};
  }, [refresh]);
  return {health, connection, checking, refresh};
}

type ServiceState = ReturnType<typeof useStudioHealth>;

export function ServiceBanner({service, onConfigure}: {service: ServiceState; onConfigure: () => void}) {
  const offline = service.connection === "offline";
  const health = service.health;
  if (health?.generation_available && health.planning_available && !health.generation_error && !health.review_error) return null;
  const title = offline ? "创作服务已断开" : service.connection === "checking" ? "正在检查服务连接" : health?.executor_state === "checking" ? "正在验证 Azure 连接" : health?.generation_error ? "生图服务需要处理" : health?.review_error ? "图片已保留，质检暂未完成" : !health?.generation_available ? "自动生图尚未配置" : "智能规划尚未配置";
  const detail = offline ? "暂时无法保存或更新任务。请恢复本地服务后重新检测；已保存的记录仍保留。" : service.connection === "checking" ? "确认服务状态后再提交任务。" : health?.executor_state === "checking" ? "认证通过后，后台会自动处理排队任务；无需重复提交。" : health?.generation_error || health?.review_error || (!health?.generation_available ? "当前任务只会排队，需执行人员手动处理；继续等待不会自动出图。可先体验示例回放。" : "可以生成图片；A+ 模块方案目前需要手动填写。");
  return <section className={`st-service-banner ${offline ? "offline" : ""}`} role="status" aria-label="服务连接状态">
    <Icon name="info" size={19}/><div><strong>{title}</strong><p>{detail}</p></div>
    <button className="st-secondary small" onClick={onConfigure}>查看配置</button>
  </section>;
}

export function ServiceConfiguration({service, onClose}: {service: ServiceState; onClose: () => void}) {
  const {health, connection, checking} = service;
  const capability = (value: boolean | undefined, yes: string, no: string) => !health ? "待检测" : value ? yes : no;
  return <Modal title="服务配置与连接状态" onClose={onClose}>
    <div className="st-service-config">
      <p className="st-service-summary">{health?.generation_available && !health.generation_error ? "自动生图已就绪，可以开始创作。" : "查看当前连接状态，按提示恢复后再继续创作。"}</p>
      <dl>
        <div><dt>创作服务</dt><dd>{connection === "online" ? "已连接" : connection === "offline" ? "连接失败" : "检测中"}</dd></div>
        <div><dt>自动生图</dt><dd>{capability(health?.generation_available, "已就绪", health?.executor_state === "error" ? "已暂停，请处理下方问题" : health?.executor_state === "checking" ? "正在验证认证" : "未接入自动执行器")}</dd></div>
        <div><dt>智能规划</dt><dd>{capability(health?.planning_available, "执行程序已配置", "未配置，可手动编辑方案")}</dd></div>
        <div><dt>Azure 接入</dt><dd>{capability(health?.azure_configured, "已配置", "当前 Studio 未接入")}</dd></div>
        <div><dt>示例回放</dt><dd>{capability(health?.demo_available, "可用，使用预置图片", "不可用")}</dd></div>
      </dl>
      {health?.generation_error && <p role="alert">{health.generation_error}</p>}
      {health?.review_error && <p role="alert">{health.review_error}</p>}
      {!health ? <div className="st-service-help"><h3>先恢复创作服务</h3><p>本地后台可能已退出。重启工作台服务后点击“重新检测”。连接恢复前无法确认模型配置，请保留当前页面中尚未保存的输入。</p></div> : health.generation_provider === "azure" ? <details className="st-service-help" open={!health.generation_available}><summary>{health.generation_available ? "Azure 自动生图已启动" : "恢复 Azure 服务"}</summary><p>{health.generation_available ? "任务会在后台依次执行，图片返回后立即保存。2K 高质量图片通常需要几分钟，具体耗时取决于模型服务。可以离开页面，稍后到创作记录查看。" : "请按上方提示恢复 Azure 登录、权限或配额，再点击重新检测。修改服务端配置文件后需要重启工作台。"}</p><p>排队任务会继续处理，无需重新提交；明确失败的任务可单独重试。结果待确认的任务不会自动重发，避免重复生成。</p></details> : !health.generation_available ? <div className="st-service-help"><h3>接下来怎么做</h3><ol>
        <li>体验流程：使用“试用示例商品”并点击“回放示例”，可以查看、编辑和导出预置作品。</li>
        <li>生成自己的图片：请部署人员接入并启动生图执行器，复用原 Azure 配置，再完成一次真实出图验证。</li>
        <li>已有排队任务会保留。执行器就绪后可继续处理，无需重复点击生成；暂不需要的任务可停止。</li>
      </ol><p>当前版本还没有网页配置密钥的功能，也不会自动读取旧版配置文件。仅准备好 Azure 密钥，无法让排队任务自动执行。</p></div> : <p className="st-note">显示“已配置”仅表示配置存在；实际出图和规划结果仍以任务反馈为准。</p>}
    </div>
    <div className="st-service-actions"><button className="st-secondary" disabled={checking} onClick={() => void service.refresh(true)}>{checking ? "检测中…" : "重新检测"}</button><button className="st-primary" onClick={onClose}>返回工作台</button></div>
  </Modal>;
}
