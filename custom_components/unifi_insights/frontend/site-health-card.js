import{It as e,J as t,N as n,X as r,a as i,f as a,it as o,j as s,n as c,p as l,rt as u,st as d,t as f,w as p,y as m}from"./chunks/register-dashboard-card-mqPoi0AV.js";f({tag:a,editorTag:l,card:class extends c{static editorTag=l;get cardType(){return`custom:${a}`}get sourceCommand(){return e}get subscribeCommand(){return`unifi_insights/site_health/subscribe`}get defaultTitle(){return`Site Health`}get headerIcon(){return o}get headerAccent(){let e=String(this.snapshot?.health?.level??`healthy`);return e===`critical`?`var(--uit-offline)`:e===`degraded`?`var(--uit-warning)`:`var(--uit-online)`}renderHeaderBadge(){if(!this.snapshot)return s;let e=this.snapshot.health??{},t=String(e.level??`unknown`);return n`<span class="chip ${t}">
            <span class="status-dot"></span>
            <span>${t}</span>
        </span>`}renderContent(){let e=this.snapshot;if(!e)return n`<div class="state">Choose site.</div>`;let i=e.health??{},a=e.gateway??{},o=e.clients??{},c=e.devices??{},l=String(i.level??`unknown`),f=String(a.internet??`unknown`),h=Number(o.total??0),g=Number(o.wired??0),_=Number(o.wireless??0),v=h>0?Math.round(_/h*100):50,y=0,b=0;for(let e of Object.values(c))if(e&&typeof e==`object`){let t=Number(e.online??0),n=Number(e.offline??0),r=Number(e.unknown??0);y+=t,b+=t+n+r}let x=typeof a.name==`string`&&a.name?a.name:`UniFi Gateway`,S=m(a.uptime_s);return n`
            <div class="hero-banner">
                <div class="hero-left">
                    ${p(u)}
                    <div>
                        <div class="hero-title">${x}</div>
                        <div class="hero-meta">
                            Status: ${l}${S?` · Uptime ${S}`:``}
                        </div>
                    </div>
                </div>
                <span class="chip ${f===`online`?`ok`:`warning`}">
                    <span class="status-dot"></span>
                    ${f}
                </span>
            </div>

            <div class="kpi-grid">
                <div class="kpi-tile">
                    <div class="kpi-top">
                        <span>Internet</span>
                        ${p(r)}
                    </div>
                    <div class="kpi-value">${f}</div>
                    <div class="kpi-sub">WAN Health · ${l}</div>
                </div>

                <div class="kpi-tile">
                    <div class="kpi-top">
                        <span>Clients</span>
                        ${p(d)}
                    </div>
                    <div class="kpi-value">${h}</div>
                    <div class="bar-track" aria-hidden="true">
                        <div
                            class="bar-fill"
                            style=${`width: ${v}%`}
                        ></div>
                    </div>
                    <div class="kpi-sub">
                        ${_||g?`${_} Wi-Fi · ${g} Wired`:`Connected clients`}
                    </div>
                </div>

                ${b>0?n`<div class="kpi-tile">
                          <div class="kpi-top">
                              <span>Devices</span>
                              ${p(t)}
                          </div>
                          <div class="kpi-value">
                              ${y}/${b}
                          </div>
                          <div class="kpi-sub">Infrastructure online</div>
                      </div>`:s}
            </div>
        `}},editor:class extends i{constructor(){super(a,e)}},name:`UniFi Site Health`,description:`Compact site health summary with WAN, gateway, device, and client status.`});