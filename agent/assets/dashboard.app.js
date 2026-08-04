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
      themeLabel: function(){ var m=this.theme; return (m==="dark"?"●":m==="light"?"○":"◐")+" Theme: "+m; }
    },
    methods: {
      toggleTile: function(k){ this.filter = (this.filter===k) ? null : k; this.tab="summary"; },
      cycleTheme: function(){ var m=["auto","light","dark"], i=(m.indexOf(this.theme)+1)%3; this.theme=m[i];
        document.documentElement.style.colorScheme = this.theme==="auto" ? "light dark" : this.theme;
        try{ localStorage.setItem("drift-theme", this.theme); }catch(e){} }
    },
    mounted: function(){
      try{ var s=localStorage.getItem("drift-theme"); if(s) this.theme=s; }catch(e){}
      document.documentElement.style.colorScheme = this.theme==="auto" ? "light dark" : this.theme;
      document.title = "Drift Detector — DevSecOps Cockpit · " + this.generated;
    }
  }).mount("#app");
})();
