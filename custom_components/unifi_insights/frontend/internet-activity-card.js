<<<<<<< HEAD
<<<<<<< HEAD
import{Dt as e,I as t,K as n,L as r,_ as i,a,et as o,g as s,j as c,k as l,n as u,o as d,s as f,t as p,w as m}from"./chunks/register-dashboard-card-DwsWPKMB.js";var h=class extends u{static editorTag=f;static properties={...u.properties,selectedWindow:{state:!0}};constructor(){super(),this.selectedWindow=`1d`}get cardType(){return`custom:${d}`}get sourceCommand(){return e}get subscribeCommand(){return`unifi_insights/internet_activity/subscribe`}get defaultTitle(){return`Internet Activity`}get headerIcon(){return o}resolveActiveWindow(e){let t=[`1h`,`1d`,`1w`,`1m`].filter(t=>t in e);return{keys:t,activeWindow:this.selectedWindow in e?this.selectedWindow:t[0]??`1d`}}renderHeaderBadge(){let e=this.snapshot?.windows??{},{keys:t,activeWindow:n}=this.resolveActiveWindow(e);return t.length<=1?l:c`
=======
import{I as e,K as t,L as n,Ot as r,_ as i,a,et as o,g as s,j as c,k as l,n as u,o as d,s as f,t as p,w as m}from"./chunks/register-dashboard-card-BJGgFLBk.js";var h=class extends u{static editorTag=f;static properties={...u.properties,selectedWindow:{state:!0}};constructor(){super(),this.selectedWindow=`1d`}get cardType(){return`custom:${d}`}get sourceCommand(){return r}get subscribeCommand(){return`unifi_insights/internet_activity/subscribe`}get defaultTitle(){return`Internet Activity`}get headerIcon(){return o}resolveActiveWindow(e){let t=[`1h`,`1d`,`1w`,`1m`].filter(t=>t in e);return{keys:t,activeWindow:this.selectedWindow in e?this.selectedWindow:t[0]??`1d`}}renderHeaderBadge(){let e=this.snapshot?.windows??{},{keys:t,activeWindow:n}=this.resolveActiveWindow(e);return t.length<=1?l:c`
>>>>>>> bc7ab1f (feat(frontend): add a tiered layout to the topology card)
=======
import{It as e,N as t,R as n,X as r,_ as i,a,at as o,g as s,j as c,n as l,o as u,s as d,t as f,w as p,z as m}from"./chunks/register-dashboard-card-mqPoi0AV.js";var h=class extends l{static editorTag=d;static properties={...l.properties,selectedWindow:{state:!0}};constructor(){super(),this.selectedWindow=`1d`}get cardType(){return`custom:${u}`}get sourceCommand(){return e}get subscribeCommand(){return`unifi_insights/internet_activity/subscribe`}get defaultTitle(){return`Internet Activity`}get headerIcon(){return o}resolveActiveWindow(e){let t=[`1h`,`1d`,`1w`,`1m`].filter(t=>t in e);return{keys:t,activeWindow:this.selectedWindow in e?this.selectedWindow:t[0]??`1d`}}renderHeaderBadge(){let e=this.snapshot?.windows??{},{keys:n,activeWindow:r}=this.resolveActiveWindow(e);return n.length<=1?c:t`
>>>>>>> 4e8e960 (feat(frontend): add a node action menu to the topology detail panel)
      <div class="pill-tabs" role="group" aria-label="Time window">
                ${n.map(e=>t`
            <button
              type="button"
              class="pill-tab"
                            aria-pressed=${String(r===e)}
              @click=${()=>{this.selectedWindow=e}}
            >
              ${e}
            </button>
          `)}
      </div>
        `}renderContent(){let e=this.snapshot;if(!e)return t`<div class="state">No data</div>`;let a=e.windows??{},{activeWindow:o}=this.resolveActiveWindow(a),l=a[o]??a[`1d`]??a[`1h`]??{},u=Number(l.download_bytes??0),d=Number(l.upload_bytes??0),f=u+d,h=`${Math.round(u/1e6)} MB`,g=`${Math.round(d/1e6)} MB`,_=`${Math.round(f/1e6)} MB`,v=f>0?Math.round(u/f*100):50,y=f>0?100-v:50,b=e.throughput??{},x=s(b.rx_bps),S=s(b.tx_bps),C=e.entity_ids??{},w=C[`download_${o}`],T=C[`upload_${o}`];return t`
            ${x||S?t`<div class="hero-banner">
            <div class="hero-left">
                          ${p(r)}
              <div>
                <div class="hero-title">Live Throughput</div>
                <div class="hero-meta">
                  ↓ ${x??`0 bps`} · ↑ ${S??`0 bps`}
                </div>
              </div>
            </div>
<<<<<<< HEAD
            <span class="chip ok"> <span class="status-dot"></span>Live </span>
          </div>`:l}
=======
                      <span class="chip ok">
                          <span class="status-dot"></span>Live
                      </span>
                  </div>`:c}
>>>>>>> 4e8e960 (feat(frontend): add a node action menu to the topology detail panel)

      <div class="kpi-grid">
        <button
          type="button"
          class="kpi-tile ${w?`clickable`:``}"
          ?disabled=${!w}
                    @click=${w?()=>this.openMoreInfo(w):c}
        >
          <div class="kpi-top">
            <span>Download</span>
                        ${p(n)}
          </div>
                    <div class="kpi-value">${i(u)}</div>
          <div class="kpi-sub">${h} · ${v}%</div>
        </button>

        <button
          type="button"
          class="kpi-tile ${T?`clickable`:``}"
          ?disabled=${!T}
                    @click=${T?()=>this.openMoreInfo(T):c}
        >
          <div class="kpi-top">
            <span>Upload</span>
                        ${p(m)}
          </div>
                    <div class="kpi-value">${i(d)}</div>
          <div class="kpi-sub">${g} · ${y}%</div>
        </button>
      </div>

      <div class="kpi-tile">
        <div class="item-top">
          <span class="kpi-top">Total Traffic (${o})</span>
          <span class="item-value">
                        ${i(f)} (${_})
          </span>
        </div>
        <div class="bar-track" aria-hidden="true">
          <div class="bar-fill" style=${`width: ${v}%`}></div>
          <div class="bar-fill secondary" style=${`width: ${y}%`}></div>
        </div>
      </div>
        `}};f({tag:u,editorTag:d,card:h,editor:class extends a{constructor(){super(u,e)}},name:`UniFi Internet Activity`,description:`Historical WAN download/upload activity and live gateway throughput.`});