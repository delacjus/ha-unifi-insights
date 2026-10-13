<<<<<<< HEAD
<<<<<<< HEAD
import{F as e,a as t,b as n,d as r,j as i,k as a,n as o,t as s,u as c,w as l,z as u}from"./chunks/register-dashboard-card-DwsWPKMB.js";s({tag:c,editorTag:r,card:class extends o{static editorTag=r;get cardType(){return`custom:${c}`}get sourceCommand(){return`unifi_insights/protect/sources`}get subscribeCommand(){return`unifi_insights/protect/subscribe`}get defaultTitle(){return`Protect Status`}get headerIcon(){return u}get includeSiteInSubscribeMessage(){return!1}getBinding(){let e=this.config.entry_id;if(e)return{entry_id:e,site_id:this.config.site_id??`*`};if(this.sources.length===1)return{entry_id:this.sources[0].entry_id,site_id:this.config.site_id??`*`}}renderHeaderBadge(){if(!this.snapshot)return a;let e=Array.isArray(this.snapshot.devices)?this.snapshot.devices:[],t=e.filter(e=>e.connected===!1).length,n=e.length-t;return i`
=======
import{F as e,a as t,b as n,d as r,j as i,k as a,n as o,t as s,u as c,w as l,z as u}from"./chunks/register-dashboard-card-BJGgFLBk.js";s({tag:c,editorTag:r,card:class extends o{static editorTag=r;get cardType(){return`custom:${c}`}get sourceCommand(){return`unifi_insights/protect/sources`}get subscribeCommand(){return`unifi_insights/protect/subscribe`}get defaultTitle(){return`Protect Status`}get headerIcon(){return u}get includeSiteInSubscribeMessage(){return!1}getBinding(){let e=this.config.entry_id;if(e)return{entry_id:e,site_id:this.config.site_id??`*`};if(this.sources.length===1)return{entry_id:this.sources[0].entry_id,site_id:this.config.site_id??`*`}}renderHeaderBadge(){if(!this.snapshot)return a;let e=Array.isArray(this.snapshot.devices)?this.snapshot.devices:[],t=e.filter(e=>e.connected===!1).length,n=e.length-t;return i`
>>>>>>> bc7ab1f (feat(frontend): add a tiered layout to the topology card)
      <span class="chip ${t>0?`warning`:`ok`}">
=======
import{L as e,N as t,V as n,a as r,b as i,d as a,j as o,n as s,t as c,u as l,w as u}from"./chunks/register-dashboard-card-mqPoi0AV.js";c({tag:l,editorTag:a,card:class extends s{static editorTag=a;get cardType(){return`custom:${l}`}get sourceCommand(){return`unifi_insights/protect/sources`}get subscribeCommand(){return`unifi_insights/protect/subscribe`}get defaultTitle(){return`Protect Status`}get headerIcon(){return n}get includeSiteInSubscribeMessage(){return!1}getBinding(){let e=this.config.entry_id;if(e)return{entry_id:e,site_id:this.config.site_id??`*`};if(this.sources.length===1)return{entry_id:this.sources[0].entry_id,site_id:this.config.site_id??`*`}}renderHeaderBadge(){if(!this.snapshot)return o;let e=Array.isArray(this.snapshot.devices)?this.snapshot.devices:[],n=e.filter(e=>e.connected===!1).length,r=e.length-n;return t`
            <span class="chip ${n>0?`warning`:`ok`}">
>>>>>>> 4e8e960 (feat(frontend): add a node action menu to the topology detail panel)
        <span class="status-dot"></span>
                ${r}/${e.length} Online
      </span>
        `}renderContent(){let r=this.snapshot;if(!r)return t`<div class="state">No Protect data</div>`;let a=Array.isArray(r.devices)?r.devices:[],s=a.filter(e=>e.connected===!1).length,c=a.length-s;return t`
      <div class="kpi-grid">
        <div class="kpi-tile">
          <div class="kpi-top">
            <span>Devices</span>
                        ${u(n)}
          </div>
                    <div class="kpi-value">${a.length}</div>
                    <div class="kpi-sub">${c} active</div>
        </div>
        <div class="kpi-tile">
          <div class="kpi-top">
            <span>Offline</span>
                        ${u(e)}
          </div>
                    <div class="kpi-value">${s}</div>
          <div class="kpi-sub">
                        ${s===0?`All connected`:`Needs attention`}
          </div>
        </div>
      </div>

      <div class="list">
                ${a.slice(0,6).map(e=>{let n=typeof e.camera_entity_id==`string`?e.camera_entity_id:void 0,r=String(e.name??`Device`),a=String(e.kind??`device`),s=e.connected!==!1,c=s?`online`:`offline`,l=`${r} · ${a}`;return t`
            <div class="item-card">
              <div class="item-icon ${c}">
                                ${u(i(a))}
              </div>
              <div class="item-body">
                <div class="item-top">
                                    ${n?t`<button
                        type="button"
                        class="link item-name"
                                              @click=${()=>this.openMoreInfo(n)}
                      >
<<<<<<< HEAD
                        ${u}
                      </button>`:i`<span class="item-name"> ${u} </span>`}
=======
                                              ${l}
                                          </button>`:t`<span class="item-name">
                                              ${l}
                                          </span>`}
>>>>>>> 4e8e960 (feat(frontend): add a node action menu to the topology detail panel)
                  <span class="chip ${c}">
                    <span class="status-dot"></span>
                    ${c}
                  </span>
                </div>
                                ${e.is_recording||e.motion_active?t`<div class="item-meta">
                                          ${e.is_recording&&s?t`<span>● Recording</span>`:o}
                                          ${e.motion_active?t`<span>· Motion detected</span>`:o}
                                      </div>`:o}
              </div>
            </div>
          `})}
      </div>
        `}},editor:class extends r{constructor(){super(l,`unifi_insights/protect/sources`)}},name:`UniFi Protect Status`,description:`Live UniFi Protect camera, doorbell, chime, and NVR status summary.`});