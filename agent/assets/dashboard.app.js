(function(){
  function blob(id){ var el=document.getElementById(id); try{ return el?JSON.parse(el.textContent):{}; }catch(e){ return {}; } }
  var DATA = blob("drift-data");
  var C = DATA.counts || {}, OWN = (C.byOwner || {});
  // the SBOM/SPDX/SARIF side-payloads (same standard-format bundle `drift-scan sbom`/`sarif`
  // write) — embedded verbatim so the dashboard's SBOM/SARIF panels and the JSON views are
  // byte-for-byte what those commands would produce. Read-only, so markRaw skips Vue's deep
  // reactivity conversion (these can be large and never mutate).
  var SBOM = blob("sbom-data"), SPDX = blob("spdx-data"), SARIF = blob("sarif-data");
  // generic scan methodology (Sources / Versions / Parked tiers / catalog note) is boilerplate,
  // identical every scan — it goes to its own "methodology" footer, NOT mixed into the
  // data-specific coverage warnings (unaudited vendors, unreachable sources, …).
  var GENERIC_NOTE = [/^Sources:/, /^Versions are/, /^Parked:/, /^Vendor API sunsets:/];
  function isGenericNote(n){ return GENERIC_NOTE.some(function(r){ return r.test(n); }); }

  // Deterministic "YYYY-MM-DD" -> a comparable day-ordinal, used ONLY to place the Retirement
  // Timeline's points and its "today" line. Pure integer arithmetic (Howard Hinnant's
  // days_from_civil) — no Date object, no wall-clock read, so two runs of the SAME drift.json
  // place every point identically. "Today" is always DATA.generated, the scan's own date —
  // reading the CURRENT wall clock instead would make the chart's own reference line
  // non-deterministic and wrong the moment the page is opened a day after the scan ran.
  function dayOrdinal(s){
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s || ""));
    if(!m) return null;
    var y = +m[1], mo = +m[2], d = +m[3];
    y -= mo <= 2 ? 1 : 0;
    var era = Math.floor((y >= 0 ? y : y - 399) / 400);
    var yoe = y - era * 400;                                              // [0, 399]
    var doy = Math.floor((153 * (mo + (mo > 2 ? -3 : 9)) + 2) / 5) + d - 1; // [0, 365]
    var doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy; // [0, 146096]
    return era * 146097 + doe;
  }

  Vue.createApp({
    data: function(){
      return {
        DATA: DATA, counts: C,
        SBOM: Vue.markRaw(SBOM), SPDX: Vue.markRaw(SPDX), SARIF: Vue.markRaw(SARIF),
        generated: DATA.generated || "",
        scope: "",            // global repo scope ("" = all)
        tab: null,             // active PRIMARY tab = the metric-tile dimension (cockpit IA);
                               // null = OVERVIEW default = no scope = the full ranked action
                               // queue in Summary. Was `filter` pre-restructure.
        sub: "summary",        // active sub-tab: summary | sbom | sarif (replaces the old
                               // top-level tab bar; "Retirement timeline" retires into the
                               // hero region — Task 2/3 — so it is not a sub-tab option)
        expanded: {},         // row drill-down: idx (within `rows`) -> open/closed
        sumView: "prev",       // Summary sub-tab: Preview | JSON · drift.json
        sbomView: "prev",      // SBOM sub-tab: Preview | CycloneDX | SPDX
        sarifView: "prev",     // SARIF sub-tab: Preview | JSON · sarif.json
        copyState: {},         // per-view "Copy"/"Copied" label for the JSON copy buttons
        q: "",
        theme: "dark"
      };
    },
    computed: {
      repoOptions: function(){
        var m = {};
        (this.DATA.actions||[]).forEach(function(a){ if(a.repo) m[a.repo]=a.repoLabel||a.repo; });
        (this.DATA.shapes||[]).forEach(function(s){ if(s.repo && !(s.repo in m)) m[s.repo]=s.repoLabel||s.repo; });
        return Object.keys(m).sort(function(a,b){ return m[a].localeCompare(m[b]); })
                     .map(function(k){ return {key:k, label:m[k]}; });
      },
      tileGroups: function(){
        var c=this.counts, o=OWN;
        // mirrors the original server-side `_own` lambda exactly: byOwner sub-dicts carry
        // lowercase "fixes"/"review" keys (see _build_projection's counts.byOwner), NOT
        // the uppercase finding-status literals — a case bug here silently zeros both tiles.
        var own=function(k){ var v=o[k]||{}; return (v.fixes||0)+(v.review||0); };
        return [
          {title:"Ownership", tiles:[
            {key:"devops",label:"DevOps",n:own("devops")},{key:"developer",label:"Developer",n:own("developer")}]},
          {title:"Security", tiles:[
            {key:"critical",label:"Critical",n:c.critical,sev:"crit"},{key:"fixes",label:"Fixes",n:c.fixes},
            {key:"eol",label:"EOL",n:c.eol}]},
          {title:"Integrations", tiles:[
            {key:"apis",label:"APIs",n:c.apis},{key:"sunsets",label:"Sunsets",n:c.sunsets},
            {key:"pastdue",label:"Past-due",n:c.pastDue,sev:"warn"},{key:"unknown",label:"Unknown",n:c.unknown},
            {key:"private",label:"Private",n:c.private},{key:"unaudited",label:"Unaudited",n:c.unaudited}]}
        ];
      },
      themeLabel: function(){ var m=this.theme; return (m==="dark"?"●":m==="light"?"○":"◐")+" Theme: "+m; },
      // ---- Summary table: mode dispatch + scope/query-filtered rows (ported from the
      // pre-Vue _CLIENT_JS: actionsFor/endpointsFor/privateFor/catalogFor + the render()
      // mode map). "mode" mirrors the vanilla state.mode; "rows" mirrors calling the right
      // …For() and feeding it to the right renderX().
      mode: function(){
        var f = this.tab;
        if(f==="apis" || f==="unknown") return "endpoints";
        if(f==="private") return "private";
        if(f==="unaudited") return "catalog";
        return "actions";
      },
      rows: function(){
        if(this.mode==="endpoints") return this.endpointsFor();
        if(this.mode==="private")   return this.privateFor();
        if(this.mode==="catalog")   return this.catalogFor();
        return this.actionsFor();
      },

      // ---- JSON views: drift.json / CycloneDX / SPDX / SARIF, pretty-printed for the
      // read-only "view / copy" panels. Same DATA/SBOM/SPDX/SARIF the tables above render
      // from — the verified source of truth, not a re-derived summary. ----
      driftJsonText: function(){ return JSON.stringify(this.DATA, null, 2); },
      sbomJsonText: function(){ return JSON.stringify(this.SBOM, null, 2); },
      spdxJsonText: function(){ return JSON.stringify(this.SPDX, null, 2); },
      sarifJsonText: function(){ return JSON.stringify(this.SARIF, null, 2); },

      // ---- SBOM preview: components (scoped to the selected repo via drift:repo properties)
      // + per-component worst vuln severity, ported from the pre-Vue renderSbom(). ----
      sbomVulnIndex: function(){
        var worst = {}, counts = {}, rank = {critical:4, high:3, medium:2, low:1, unknown:0};
        (this.SBOM.vulnerabilities || []).forEach(function(v){
          var sev = ((v.ratings || [{}])[0] || {}).severity || "unknown";
          (v.affects || []).forEach(function(a){
            if(!(a.ref in worst) || rank[sev] > rank[worst[a.ref]]) worst[a.ref] = sev;
            counts[a.ref] = (counts[a.ref] || 0) + 1;
          });
        });
        return {worst: worst, counts: counts};
      },
      sbomComponents: function(){
        var self = this, all = this.SBOM.components || [];
        if(!this.scope) return all;
        return all.filter(function(c){ return self.componentRepos(c).indexOf(self.scope) > -1; });
      },
      sbomRows: function(){
        var self = this, idx = this.sbomVulnIndex;
        return this.sbomComponents.map(function(c){
          var ref = c["bom-ref"], n = idx.counts[ref] || 0, sev = idx.worst[ref];
          return {
            type: c.type, purl: c.purl || c["bom-ref"], version: c.version || "",
            repoCount: self.componentRepos(c).length,
            vulnCount: n, vulnSeverity: sev,
            pillClass: sev === "critical" ? "crit" : sev === "high" ? "high"
                     : sev === "medium" ? "med" : "low"
          };
        });
      },
      sbomHeaderText: function(){
        var n = this.sbomComponents.length, vulns = (this.SBOM.vulnerabilities || []).length;
        return "Components — " + n + (this.scope ? (" in " + this.repoLabelOf(this.scope)) : "")
             + "  ·  " + vulns + " vulnerabilities";
      },

      // ---- SARIF preview: results grouped by rule, scoped to the selected repo via the
      // uri prefix (results carry no repo field of their own, just file:line uris rooted at
      // the repo path) — ported from the pre-Vue renderSarif(). ----
      sarifAllResults: function(){ return ((this.SARIF.runs || [{}])[0] || {}).results || []; },
      sarifResults: function(){
        var self = this;
        if(!this.scope) return this.sarifAllResults;
        return this.sarifAllResults.filter(function(r){
          return self.sarifUri(r).indexOf(self.scope + "/") === 0; });
      },
      sarifGroups: function(){
        var byRule = {};
        this.sarifResults.forEach(function(r){ (byRule[r.ruleId] = byRule[r.ruleId] || []).push(r); });
        return Object.keys(byRule).sort().map(function(rid){
          var list = byRule[rid];
          return {
            ruleId: rid, count: list.length,
            rows: list.slice(0, 200).map(function(r){
              var pl = ((r.locations || [])[0] || {}).physicalLocation || {};
              var uri = (pl.artifactLocation || {}).uri || "";
              var line = (pl.region || {}).startLine;
              return {
                where: uri + (line ? (":" + line) : ""),
                message: (r.message || {}).text || "",
                level: r.level || "note",
                pillClass: r.level === "error" ? "crit" : r.level === "warning" ? "high" : "low"
              };
            })
          };
        });
      },
      sarifHeaderText: function(){
        return "Findings — " + this.sarifResults.length + " results"
             + (this.scope ? (" in " + this.repoLabelOf(this.scope)) : "") + ", grouped by rule";
      },

      // ---- coverage / "changed since last scan" / methodology footer — the honest
      // "how complete was this scan" context, out of the data (findings) plane. "Cannot see"
      // must never render as "clean": the rootsUnscannable block below is the load-bearing
      // one — it is the only thing standing between a repo the scanner couldn't open and a
      // report that looks green over it. ----
      rootsUnscannable: function(){ return this.DATA.rootsUnscannable || []; },
      coverageNotesSpecific: function(){
        return (this.DATA.coverageNotes || []).filter(function(n){ return !isGenericNote(n); });
      },
      methodologyNotes: function(){
        return (this.DATA.coverageNotes || []).filter(isGenericNote);
      },
      unknownShapes: function(){
        return (this.DATA.shapes || []).filter(function(s){ return s.verdict === "UNKNOWN"; });
      },
      gradedRepos: function(){
        return (this.DATA.coverageGrades || []).filter(function(g){ return g.grade !== "HIGH"; });
      },
      sdkMediated: function(){ return this.DATA.sdkMediated || []; },
      coveredDeps: function(){ return this.DATA.coveredDeps || []; },
      coverageHasContent: function(){
        return this.rootsUnscannable.length > 0 || this.coverageNotesSpecific.length > 0 ||
               this.unknownShapes.length > 0 || this.gradedRepos.length > 0 ||
               this.sdkMediated.length > 0 || this.coveredDeps.length > 0;
      },
      inventoryDrift: function(){ return this.DATA.inventoryDrift || null; },
      driftChangeRows: function(){
        var d = this.inventoryDrift; if(!d) return [];
        return (d.changes || []).map(function(c){
          var bits = [];
          (c.endpointsAdded || []).forEach(function(e){ bits.push("+ endpoint " + e); });
          (c.endpointsRemoved || []).forEach(function(e){ bits.push("− endpoint " + e); });
          (c.sdkVersionChanges || []).forEach(function(s){ bits.push(s.pkg + " " + s.from + " → " + s.to); });
          (c.sdksAdded || []).forEach(function(s){ bits.push("+ " + s.pkg + " " + s.ver); });
          (c.sdksRemoved || []).forEach(function(s){ bits.push("− " + s.pkg + " " + s.ver); });
          (c.runtimeChanges || []).forEach(function(r){ bits.push(r.product + " " + r.from + " → " + r.to); });
          return {repo: c.repo, bits: bits};
        }).filter(function(chg){ return chg.bits.length > 0; });
      },
      driftHasContent: function(){
        var d = this.inventoryDrift; if(!d) return false;
        return !!((d.reposAdded && d.reposAdded.length) || (d.reposRemoved && d.reposRemoved.length) ||
               this.driftChangeRows.length > 0);
      },

      // ---- the Retirement Timeline (Task 6): every sunset action plotted by date, "today"
      // = DATA.generated (never the wall clock). NONE silently dropped — a sunset is either a
      // dated point on the axis (timeline.dated) or a chip in the undated lane
      // (timeline.undated); verify.check_timeline_lanes enforces that the template still
      // references BOTH lanes, so deleting either one (hiding deprecated-no-date sunsets,
      // say) fails verify instead of only a screenshot nobody looks at.
      // Respects the global repo scope like every other view.
      timeline: function(){
        var self = this;
        var genOrd = dayOrdinal(this.generated);
        var sunsets = (this.DATA.actions || []).filter(function(a){
          return a.kind === "sunset" && self.matchesRepo(a.repo);
        });
        var datedActions = sunsets.filter(function(a){ return !!a.date; });
        var undatedActions = sunsets.filter(function(a){ return !a.date; });

        var label = function(a){
          return (a.repoLabel || a.repo) + " · " + a.ref + (a.unit ? " — " + a.unit : "");
        };

        if(!datedActions.length){
          return {
            dated: [],
            undated: undatedActions.map(function(a){
              return {repo: a.repoLabel || a.repo, vendor: a.ref, unit: a.unit,
                      label: label(a) + " · date unknown"};
            }),
            genX: null
          };
        }

        var ords = datedActions.map(function(a){ return dayOrdinal(a.date); });
        var allOrds = genOrd === null ? ords : ords.concat([genOrd]);
        var minOrd = Math.min.apply(null, allOrds), maxOrd = Math.max.apply(null, allOrds);
        var span = Math.max(1, maxOrd - minOrd);
        var PAD = 30, W = 940;                          // matches the <svg viewBox="0 0 1000 220">
        var xOf = function(o){ return PAD + ((o - minOrd) / span) * W; };

        var dated = datedActions.map(function(a, i){
          var o = dayOrdinal(a.date);
          var pastDue = genOrd !== null && o < genOrd;
          var up = i % 2 === 0;                          // alternate stems so labels don't collide
          return {
            x: xOf(o), y: 130,
            color: pastDue ? "var(--crit)" : "var(--sun)",
            pastDue: pastDue,
            date: a.date,
            stemY: up ? 96 : 164,
            labelY: up ? 88 : 180,
            label: label(a) + " · " + a.date + (pastDue ? " (past-due)" : " (upcoming)")
          };
        }).sort(function(pa, pb){ return pa.x - pb.x; });

        return {
          dated: dated,
          undated: undatedActions.map(function(a){
            return {repo: a.repoLabel || a.repo, vendor: a.ref, unit: a.unit,
                    label: label(a) + " · date unknown"};
          }),
          genX: genOrd === null ? null : xOf(genOrd)
        };
      }
    },
    methods: {
      // ---- toggleTab: set the active primary tab (the metric-tile dimension), or clear it
      // back to null (OVERVIEW — no scope, the full ranked action queue) if it's already
      // active. Was toggleTile/`filter` pre-restructure; same toggle semantics. ----
      toggleTab: function(k){ this.tab = (this.tab===k) ? null : k; },
      cycleTheme: function(){ var m=["auto","light","dark"], i=(m.indexOf(this.theme)+1)%3; this.theme=m[i];
        document.documentElement.style.colorScheme = this.theme==="auto" ? "light dark" : this.theme;
        try{ localStorage.setItem("drift-theme", this.theme); }catch(e){} },

      // ---- the global repo scope (the #repo-filter select, "" = all). Applies to actions,
      // endpoints AND private — the bug fixed earlier was that it only gated actions. Catalog
      // is vendor-level/fleet-wide and stays unscoped, as in the vanilla engine. ----
      matchesRepo: function(repo){ return !this.scope || repo === this.scope; },
      matchesQ: function(text){ return !this.q || String(text).toLowerCase().indexOf(this.q.toLowerCase()) > -1; },

      // Scheme allow-list for any href built from scan data: only http/https become clickable
      // links; javascript:/data:/etc. fall back to plain (already auto-escaped) text. Ports
      // the vanilla safeUrl() — the client-side XSS guard esc/escA/safeUrl provided before
      // Task 3 removed the old string-built rows. Vue's {{ }} / :attr bindings now do the
      // escaping job of esc()/escA(); safeUrl still has to do ITS job (scheme gating) because
      // auto-escaping alone does not stop a clickable javascript: URI from executing on click.
      safeUrl: function(u){ u = String(u==null ? "" : u); return /^https?:\/\//i.test(u) ? u : null; },

      copyText: function(text){ if(navigator.clipboard) navigator.clipboard.writeText(text); },

      actionsFor: function(){
        var f = this.tab, self = this;
        return (this.DATA.actions || []).filter(function(a){
          if(!self.matchesRepo(a.repo)) return false;                 // global repo scope
          // the retiring operation is part of the identity, so it must be searchable too —
          // a PM filtering for "GetCategoryFeatures" has to land on its row
          var label = a.ref + (a.unit ? " " + a.unit : "");
          if(!self.matchesQ((a.repoLabel || a.repo || "") + " " + label)) return false;
          if(f==="critical")  return a.worst==="CRITICAL";
          if(f==="fixes")     return a.status==="DEPRECATED";
          if(f==="eol")       return a.kind==="eol";
          if(f==="devops")    return a.owner==="devops";               // the two delivery streams
          if(f==="developer") return a.owner==="developer";
          if(f==="sunsets")   return a.kind==="sunset";
          // "Past-due" = a sunset already retired (DEPRECATED with a passed date) — an
          // integration broken NOW, distinct from an upcoming deadline or a CVE fix.
          if(f==="pastdue")   return a.kind==="sunset" && a.status==="DEPRECATED" && a.date;
          return true;
        });
      },
      endpointsFor: function(){
        var f = this.tab, self = this;
        return (this.DATA.endpoints || []).filter(function(e){
          if(!self.matchesRepo(e.repo)) return false;                  // global repo scope
          if(!self.matchesQ((e.repo || "") + " " + (e.domain || "") + " " + (e.vendor || ""))) return false;
          if(f==="unknown") return !e.classified;
          if(f==="apis")    return e.classified;
          return true;
        });
      },
      privateFor: function(){
        var self = this;
        return (this.DATA.private || []).filter(function(p){
          // Private tile honours the repo scope too
          return self.matchesRepo(p.repo) && self.matchesQ((p.repo || "") + " " + (p.source || ""));
        });
      },
      catalogFor: function(){
        var self = this;
        return (this.DATA.catalog || []).filter(function(cv){
          return cv.verdict !== "CURRENT" && self.matchesQ((cv.vendor || "") + " " + (cv.verdict || ""));
        });
      },

      actionLabel: function(a){ return a.ref + (a.unit ? " " + a.unit : ""); },
      targetText: function(a){
        return a.fix_version ? (a.current_version + " → " + a.fix_version) : (a.recommendation || "review");
      },
      catalogWhy: function(cv){
        if(cv.verdict==="UNAUDITED"){
          return cv.catalogEntries
            ? cv.catalogEntries + " catalog entr(y/ies), but the vendor's page has never been reconciled"
            : "no catalog entries at all";
        }
        return "last checked " + (cv.checked || "?") + " — re-check the vendor's page";
      },

      // ---- row drill-down: inline-accordion, one flag per row (keyed by its position in
      // the current `rows`). Only actions/endpoints rows expand — private/catalog rows never
      // had a click handler in the vanilla engine either. ----
      onRowClick: function(idx){ if(this.mode==="actions" || this.mode==="endpoints") this.toggleRow(idx); },
      toggleRow: function(idx){ this.expanded[idx] = !this.expanded[idx]; },

      // ---- SBOM/SARIF repo-scope helpers ----
      componentRepos: function(c){
        return (c.properties || []).filter(function(pr){ return pr.name === "drift:repo"; })
                                    .map(function(pr){ return pr.value; });
      },
      sarifUri: function(r){
        var l = (r.locations || [])[0];
        return ((l && l.physicalLocation || {}).artifactLocation || {}).uri || "";
      },
      repoLabelOf: function(k){
        var opt = this.repoOptions.filter(function(o){ return o.key === k; })[0];
        return opt ? opt.label : k;
      },

      // ---- JSON view/copy panels (drift.json / CycloneDX / SPDX / SARIF): copy-to-clipboard
      // with a brief "Copied" acknowledgement, keyed per view so the four panels' buttons
      // don't share state. ----
      copyJson: function(key, text){
        var self = this;
        var done = function(){ self.copyState[key] = "Copied";
          setTimeout(function(){ self.copyState[key] = "Copy"; }, 1200); };
        if(navigator.clipboard) navigator.clipboard.writeText(text).then(done, done);
        else done();
      },
      copyLabel: function(key){ return this.copyState[key] || "Copy"; },

      // ---- Task 7: deep-linkable state — scope ("repo") and the active primary tab ("tab")
      // round-trip through the URL query string so a delivered issue (e.g. "APIs, scoped to
      // repo X") can link straight to that view. `q` (the free-text search box) is
      // deliberately NOT written here: it's transient per-session input, not a "view" worth
      // bookmarking, and syncing it would rewrite the address bar on every keystroke.
      // INTERIM (Task 1 of the cockpit IA restructure): only `repo`/`tab` round-trip today;
      // `sub` (Summary/SBOM/SARIF) does not participate in the URL yet — the full
      // `?repo=&tab=&sub=` reconciliation is Task 4. Only non-default values are written, so
      // the clean/default view keeps a clean URL, and history.replaceState (not pushState) is
      // used so every tab click doesn't spam Back.
      syncUrl: function(){
        try{
          var params = new URLSearchParams();
          if(this.scope) params.set("repo", this.scope);
          if(this.tab) params.set("tab", this.tab);
          var qs = params.toString();
          var url = location.pathname + (qs ? "?" + qs : "") + location.hash;
          history.replaceState(null, "", url);
        }catch(e){}
      }
    },
    watch: {
      // any change to WHAT is shown (primary tab, repo scope, search text) closes every open
      // detail row — mirrors the vanilla render(), which rebuilt the whole <tbody> (and so
      // discarded every row's open/closed state) on every tile click / scope change / keystroke.
      // It also (tab/scope only) re-syncs the URL — see the Task 7 note on syncUrl above.
      tab: function(){ this.expanded = {}; this.syncUrl(); },
      scope: function(){ this.expanded = {}; this.syncUrl(); },
      q: function(){ this.expanded = {}; }
    },
    mounted: function(){
      try{ var s=localStorage.getItem("drift-theme"); if(s) this.theme=s; }catch(e){}
      document.documentElement.style.colorScheme = this.theme==="auto" ? "light dark" : this.theme;
      document.title = "Drift Detector — DevSecOps Cockpit · " + this.generated;

      // ---- Task 7: seed scope/tab from the URL on load. Every value is validated against
      // the known-good option lists (repoOptions / tile keys) before being assigned — an
      // unknown or stale param (a repo that no longer exists, a typo'd tab) is silently
      // ignored and the default view renders, never a throw. `sub` is not seeded here yet
      // (Task 4 — see the syncUrl note above).
      try{
        var params = new URLSearchParams(location.search);
        var repo = params.get("repo");
        if(repo && this.repoOptions.some(function(o){ return o.key === repo; })) this.scope = repo;
        var tab = params.get("tab");
        var knownTabs = [];
        this.tileGroups.forEach(function(g){ g.tiles.forEach(function(t){ knownTabs.push(t.key); }); });
        if(tab && knownTabs.indexOf(tab) > -1) this.tab = tab;
      }catch(e){}
      this.syncUrl();
    }
  }).mount("#app");
})();
