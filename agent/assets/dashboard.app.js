(function(){
  function blob(id){ var el=document.getElementById(id); try{ return el?JSON.parse(el.textContent):{}; }catch(e){ return {}; } }
  var DATA = blob("drift-data");
  var C = DATA.counts || {}, OWN = (C.byOwner || {});

  Vue.createApp({
    data: function(){
      return {
        DATA: DATA, counts: C,
        generated: DATA.generated || "",
        scope: "",            // global repo scope ("" = all)
        filter: null,         // active tile filter
        expanded: {},         // row drill-down: idx (within `rows`) -> open/closed
        tab: "summary",
        q: "",
        theme: "dark",
        tabs: [{id:"summary",label:"Summary"},{id:"timeline",label:"Retirement timeline"},
               {id:"sbom",label:"SBOM"},{id:"sarif",label:"SARIF"}]
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
        var f = this.filter;
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
      }
    },
    methods: {
      toggleTile: function(k){ this.filter = (this.filter===k) ? null : k; this.tab="summary"; },
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
        var f = this.filter, self = this;
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
        var f = this.filter, self = this;
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
      toggleRow: function(idx){ this.expanded[idx] = !this.expanded[idx]; }
    },
    watch: {
      // any change to WHAT is shown (tile filter, repo scope, search text) closes every open
      // detail row — mirrors the vanilla render(), which rebuilt the whole <tbody> (and so
      // discarded every row's open/closed state) on every tile click / scope change / keystroke.
      filter: function(){ this.expanded = {}; },
      scope: function(){ this.expanded = {}; },
      q: function(){ this.expanded = {}; }
    },
    mounted: function(){
      try{ var s=localStorage.getItem("drift-theme"); if(s) this.theme=s; }catch(e){}
      document.documentElement.style.colorScheme = this.theme==="auto" ? "light dark" : this.theme;
      document.title = "Drift Detector — DevSecOps Cockpit · " + this.generated;
    }
  }).mount("#app");
})();
