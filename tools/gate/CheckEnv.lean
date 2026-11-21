import Lean

/-!
# Trusted environment checker of the contribution gate

    lean --run tools/gate/CheckEnv.lean <request.json> <out.json>

run with the upstream checkout as working directory and `LEAN_PATH` pointing
at its build (tools/gate/env_facts.py computes both). This file imports only
`Lean`: nothing a pull request adds can influence how the checker itself is
elaborated. The pull request's modules are loaded at run time, as data:

* `importModules` with the default level `OLeanLevel.private`, which imports
  every module as if by `import all`: the `.olean.private` part of every
  module of the module system is read, so private declarations, theorem
  bodies and auxiliary constants of the target are all visible.
* `loadExts := false` and no plugins: environment extensions are not
  initialised from the imported data, so no `initialize` code, attribute
  handler or interpreted extension of the loaded modules ever runs. The
  initializer-execution flag is also reset (`withImporting`) before importing.
  Extension data we report (declaration ranges, `implemented_by`, `extern`,
  `meta` marks, structure info) is read from the raw per-module entries.

Facts are computed from `ConstantInfo` values only. Statements are printed by
a structural printer defined below (no `ppExpr`, no delaborator, no
unexpander), so notation or pretty-printer extensions in the loaded
environment cannot change what is compared.

Request (JSON): `modules` (names to import), `target_prefix` (module prefix
of the target), `protected` (declaration names), `roots` (extra roots for
`reachable`), `closure_prefixes` (name or module prefixes whose constants are
unfolded into a statement closure), `forbidden_prefixes` (name prefixes that
mark metaprogramming when a target constant refers to a non-proof constant
under them), `autoparam_refs` (what an auto-parameter syntax constant may
refer to), `replay` (re-check every target constant in the kernel on top of
the target's outside imports, as lean4checker does, with
`Lean.Kernel.Environment.replay`), optional `emit_refs` (list every
referenced constant) and `max_closure_bytes`.

Output (JSON): `protected` {name: {exists, kind, module, level_params,
closure {dump, members, missing, error}, axioms, axioms_missing}},
`constants` {name: {k, m, unsafe, partial, impl, extern, meta, forbidden,
range, uses, autoparam, wf_rec, home?, refs?}}, `roots`, `reachable`,
`forbidden_prefixes_seen`, `replay` {ran, ok, ms, load_ms, constants,
base_imports, error}, `ms`, `lean_version`. Exit status 0 when the output was
written, 1 when a module failed to load or the request is invalid.
-/

open Lean

namespace GateCheck

/-! ## Structural printing -/

/-- A name component that needs no quoting. -/
def plainComp (s : String) : Bool :=
  match s.toList with
  | [] => false
  | c :: cs => (c.isAlpha || c == '_') &&
      cs.all fun c => c.isAlphanum || c == '_' || c == '\'' || c == '!' || c == '?'

def quoteComp (s : String) : String :=
  (s.foldl (fun acc c => if c == '\\' || c == '«' || c == '»' then (acc.push '\\').push c else acc.push c)
    "«").push '»'

def compStr (s : String) : String := if plainComp s then s else quoteComp s

/-- Injective rendering of a name: plain components never contain `.`, `#`
or `«`; other string components are quoted; numeric ones are `#n`. -/
def nameStr : Name → String
  | .anonymous => "[]"
  | .str .anonymous s => compStr s
  | .str p s => nameStr p ++ "." ++ compStr s
  | .num .anonymous n => "#" ++ toString n
  | .num p n => nameStr p ++ ".#" ++ toString n

def indexIn (xs : List Name) (n : Name) : Option Nat :=
  go xs 0
where
  go : List Name → Nat → Option Nat
    | [], _ => none
    | x :: xs, i => if x == n then some i else go xs (i + 1)

/-- Universe levels; the declaration's own universe parameters are printed by
position (`u0`, `u1`, …), so renaming them does not change the dump. -/
def lvlStr (lps : List Name) : Level → String
  | .zero => "0"
  | .succ l => "(s " ++ lvlStr lps l ++ ")"
  | .max a b => "(max " ++ lvlStr lps a ++ " " ++ lvlStr lps b ++ ")"
  | .imax a b => "(imax " ++ lvlStr lps a ++ " " ++ lvlStr lps b ++ ")"
  | .param n => match indexIn lps n with
    | some i => "u" ++ toString i
    | none => "(param " ++ nameStr n ++ ")"
  | .mvar m => "(lmvar " ++ nameStr m.name ++ ")"

def biStr : BinderInfo → String
  | .default => "d" | .implicit => "i" | .strictImplicit => "s" | .instImplicit => "c"

structure SerState where
  parts : Array String := #[]
  bytes : Nat := 0

abbrev SerM := ReaderT Nat (StateT SerState (Except String))

def emit (s : String) : SerM Unit := do
  modify fun st => { st with parts := st.parts.push s, bytes := st.bytes + s.utf8ByteSize }
  let limit ← read
  if (← get).bytes > limit then
    throw s!"structural dump exceeds {limit} bytes"

/-- Kernel terms as S-expressions. Binder names are omitted (terms are
compared up to α-equivalence); binder info is kept; metadata is transparent;
applications are binary so that metadata inside a spine cannot matter. -/
partial def ser (lps : List Name) : Expr → SerM Unit
  | .bvar i => emit ("#" ++ toString i)
  | .fvar id => emit ("(fvar " ++ nameStr id.name ++ ")")
  | .mvar id => emit ("(mvar " ++ nameStr id.name ++ ")")
  | .sort l => emit ("(sort " ++ lvlStr lps l ++ ")")
  | .const n ls => emit ("(const " ++ nameStr n ++ " [" ++ " ".intercalate (ls.map (lvlStr lps)) ++ "])")
  | .app f a => do emit "(@ "; ser lps f; emit " "; ser lps a; emit ")"
  | .lam _ t b bi => do emit ("(fun " ++ biStr bi ++ " "); ser lps t; emit " "; ser lps b; emit ")"
  | .forallE _ t b bi => do emit ("(pi " ++ biStr bi ++ " "); ser lps t; emit " "; ser lps b; emit ")"
  | .letE _ t v b _ => do emit "(let "; ser lps t; emit " "; ser lps v; emit " "; ser lps b; emit ")"
  | .lit (.natVal n) => emit ("(nat " ++ toString n ++ ")")
  | .lit (.strVal s) => emit ("(str " ++ s.quote ++ ")")
  | .mdata _ e => ser lps e
  | .proj s i e => do emit ("(proj " ++ nameStr s ++ " " ++ toString i ++ " "); ser lps e; emit ")"

def kindStr : ConstantInfo → String
  | .thmInfo _ => "theorem" | .defnInfo _ => "def" | .axiomInfo _ => "axiom"
  | .opaqueInfo _ => "opaque" | .inductInfo _ => "inductive" | .ctorInfo _ => "ctor"
  | .recInfo _ => "recursor" | .quotInfo _ => "quot"

def safetyStr : DefinitionSafety → String
  | .safe => "safe" | .unsafe => "unsafe" | .partial => "partial"

def quotKindStr : QuotKind → String
  | .type => "type" | .ctor => "ctor" | .lift => "lift" | .ind => "ind"

def namesStr (ns : List Name) : String := "[" ++ " ".intercalate (ns.map nameStr) ++ "]"

/-- One line per constant. Theorems contribute their statement only (proofs
are irrelevant); definitions and opaque constants their value as well;
inductive types their shape and constructors (recursors are determined by
the inductive type and are not printed). -/
def dumpConst (ci : ConstantInfo) : SerM Unit := do
  let lps := ci.levelParams
  let head := kindStr ci ++ " " ++ nameStr ci.name ++ " u" ++ toString lps.length
  match ci with
  | .thmInfo v => do emit (head ++ " : "); ser lps v.type
  | .defnInfo v => do
    emit (head ++ " " ++ safetyStr v.safety ++ " : "); ser lps v.type; emit " := "; ser lps v.value
  | .opaqueInfo v => do
    emit (head ++ s!" unsafe={v.isUnsafe} : "); ser lps v.type; emit " := "; ser lps v.value
  | .axiomInfo v => do emit (head ++ s!" unsafe={v.isUnsafe} : "); ser lps v.type
  | .quotInfo v => do emit (head ++ " " ++ quotKindStr v.kind ++ " : "); ser lps v.type
  | .inductInfo v => do
    emit (head ++ s!" params={v.numParams} indices={v.numIndices} rec={v.isRec} unsafe={v.isUnsafe} " ++
      s!"reflexive={v.isReflexive} nested={v.numNested} all={namesStr v.all} ctors={namesStr v.ctors} : ")
    ser lps v.type
  | .ctorInfo v => do
    emit (head ++ s!" of={nameStr v.induct} idx={v.cidx} params={v.numParams} fields={v.numFields} " ++
      s!"unsafe={v.isUnsafe} : ")
    ser lps v.type
  | .recInfo v => do emit (head ++ s!" all={namesStr v.all} : "); ser lps v.type
  emit "\n"

/-! ## Statement closure and axioms -/

structure Closure where
  dump : String
  members : Array Name
  missing : Array Name

/-- The statement closure of `root`: its statement, and recursively every
constant in scope mentioned by a statement or by the value of a definition in
the closure. -/
def closureOf (env : Environment) (inScope : Name → Bool) (limit : Nat) (root : Name) :
    Except String Closure := do
  let mut todo : Array Name := #[root]
  let mut seen : NameSet := {}
  let mut members : NameMap ConstantInfo := {}
  let mut missing : Array Name := #[]
  let push (todo : Array Name) (e : Expr) : Array Name :=
    e.getUsedConstants.foldl (fun t c => if inScope c then t.push c else t) todo
  while h : todo.size > 0 do
    let n := todo[todo.size - 1]
    todo := todo.pop
    if seen.contains n then continue
    seen := seen.insert n
    match env.find? n with
    | none => missing := missing.push n
    | some ci =>
      match ci with
      | .ctorInfo v => todo := todo.push v.induct
      | .recInfo v => todo := todo ++ v.all.toArray
      | .inductInfo v =>
        members := members.insert n ci
        todo := push todo v.type
        for c in v.ctors do
          seen := seen.insert c
          match env.find? c with
          | some cci => members := members.insert c cci; todo := push todo cci.type
          | none => missing := missing.push c
      | .thmInfo v => members := members.insert n ci; todo := push todo v.type
      | .defnInfo v => members := members.insert n ci; todo := push (push todo v.type) v.value
      | .opaqueInfo v => members := members.insert n ci; todo := push (push todo v.type) v.value
      | _ => members := members.insert n ci; todo := push todo ci.type
  let sorted := (members.toList.map (fun (n, ci) => (nameStr n, ci))).toArray.qsort (fun a b => a.1 < b.1)
  let act : SerM Unit := do
    emit "closure-v1\n"
    for (_, ci) in sorted do dumpConst ci
  let ((), st) ← (act.run limit).run {}
  return { dump := String.join st.parts.toList, members := sorted.map (·.2.name),
           missing := missing.qsort (nameStr · < nameStr ·) }

/-- Axioms reachable from `root` through types, values, constructors and
recursors, walking the loaded constants (no precomputed extension data). -/
def axiomsOf (env : Environment) (root : Name) : Array Name × Array Name := Id.run do
  let mut todo : Array Name := #[root]
  let mut seen : Std.HashSet Name := {}
  let mut axs : NameSet := {}
  let mut missing : NameSet := {}
  while h : todo.size > 0 do
    let n := todo[todo.size - 1]
    todo := todo.pop
    if seen.contains n then continue
    seen := seen.insert n
    match env.find? n with
    | none => missing := missing.insert n
    | some ci =>
      if ci matches .axiomInfo _ then axs := axs.insert n
      for c in ci.getUsedConstantsAsSet do
        unless seen.contains c do todo := todo.push c
  return (axs.toArray.qsort Name.lt, missing.toArray.qsort Name.lt)

/-! ## Request -/

structure Request where
  modules : Array Name
  targetPrefix : Name
  protectedNames : Array Name
  roots : Array Name
  closurePrefixes : Array Name
  forbiddenPrefixes : Array Name
  autoParamRefs : Array Name
  replay : Bool
  emitRefs : Bool
  maxClosureBytes : Nat

def strArray (j : Json) (k : String) : Except String (Array String) := do
  match j.getObjValD k with
  | .null => return #[]
  | .arr xs => xs.mapM fun x => match x with
    | .str s => pure s
    | _ => throw s!"request field {k}: expected strings"
  | _ => throw s!"request field {k}: expected an array"

def parseName (s : String) : Except String Name :=
  let n := s.toName
  if n.isAnonymous then throw s!"not a name: {s.quote}" else pure n

def parseRequest (j : Json) : Except String Request := do
  let modules ← (← strArray j "modules").mapM parseName
  let targetPrefix ← match j.getObjValD "target_prefix" with
    | .str s => parseName s
    | _ => throw "request field target_prefix: expected a string"
  let protectedNames ← (← strArray j "protected").mapM parseName
  let roots ← (← strArray j "roots").mapM parseName
  let closurePrefixes ← (← strArray j "closure_prefixes").mapM parseName
  let forbiddenPrefixes ← (← strArray j "forbidden_prefixes").mapM parseName
  let autoParamRefs ← (← strArray j "autoparam_refs").mapM parseName
  let replay := (j.getObjValD "replay").getBool?.toOption.getD false
  let emitRefs := (j.getObjValD "emit_refs").getBool?.toOption.getD false
  let maxClosureBytes := (j.getObjValD "max_closure_bytes").getNat?.toOption.getD (64 * 1024 * 1024)
  if modules.isEmpty then throw "request lists no modules"
  return { modules, targetPrefix, protectedNames, roots, closurePrefixes, forbiddenPrefixes, autoParamRefs, replay,
           emitRefs, maxClosureBytes }

/-! ## Run -/

def nameJ (n : Name) : Json := .str n.toString
def namesJ (ns : Array Name) : Json := .arr (ns.map nameJ)

def usedConsts (ci : ConstantInfo) : NameSet :=
  let s := ci.type.getUsedConstantsAsSet
  match ci.value? (allowOpaque := true) with
  | some v => v.getUsedConstantsAsSet.foldl (fun s c => s.insert c) s
  | none => s

/-- Whether `c` is a proof: a theorem, or a constant whose type is a
proposition (cheap syntactic test as in `finalizeImport`: strip the binders,
look up the head of the conclusion and check that it returns `Prop` when
applied to that many arguments). Proofs are erased and never run, so a
reference to one is not metaprogramming even under a forbidden prefix (e.g.
`Lean.Meta.FastSubsingleton.elim`, which `congr!` proofs use). -/
def isProofConst (env : Environment) (c : Name) : Bool := Id.run do
  let some ci := env.find? c | return false
  if ci matches .thmInfo _ then return true
  let mut ty := ci.type.consumeMData
  while ty.isForall do
    let .forallE _ _ b _ := ty | return false
    ty := b.consumeMData
  let .const n _ := ty.getAppFn | return false
  let some d := env.find? n | return false
  let mut p := d.type.consumeMData
  for _ in [0:ty.getAppNumArgs] do
    let .forallE _ _ b _ := p | return false
    p := b.consumeMData
  return p.isProp

/-- The syntax constant `f._auto_n` that Lean stores for an auto-parameter
`(h : P := by tac)`: a safe definition of type `Lean.Syntax` whose value only
builds syntax (references within `allowed`). It is data that the elaborator
reads as a tactic block at use sites, like any `by` block in the source. -/
def isAutoParamSyntax (allowed : Array Name) (ci : ConstantInfo) : Bool :=
  match ci.name, ci with
  | .str _ last, .defnInfo v =>
    last.startsWith "_auto" && v.safety == .safe && v.type.consumeMData == .const ``Lean.Syntax [] &&
      v.value.getUsedConstants.all fun r => allowed.any (·.isPrefixOf r)
  | _, _ => false

/-- The `f._unsafe_rec` copy that Lean compiles for a definition `f` by
well-founded recursion: a `partial` definition next to a safe definition `f`
of the same module. -/
def isWfUnsafeRec (env : Environment) (inSameModule : Name → Bool) (ci : ConstantInfo) : Bool :=
  match ci.name, ci with
  | .str f "_unsafe_rec", .defnInfo v =>
    v.safety == .partial && inSameModule f &&
      (match env.find? f with
       | some (.defnInfo fv) => fv.safety == .safe
       | _ => false)
  | _, _ => false

def elapsed (t0 : Nat) : IO Nat := return (← IO.monoMsNow) - t0

def replayTarget (env : Environment) (isTarget : Name → Bool) (targetIdxs : Array Nat) : IO Json := do
  let t0 ← IO.monoMsNow
  let mut imports : Array Import := #[]
  let mut seenImp : NameSet := {}
  for i in targetIdxs do
    for imp in env.header.moduleData[i]!.imports do
      unless isTarget imp.module || seenImp.contains imp.module do
        seenImp := seenImp.insert imp.module
        imports := imports.push { module := imp.module }
  let mut newConsts : Std.HashMap Name ConstantInfo := {}
  for i in targetIdxs do
    for ci in env.header.moduleData[i]!.constants do
      newConsts := newConsts.insert ci.name ci
  try
    let base ← importModules imports {} (loadExts := false)
    let tLoad ← elapsed t0
    for m in base.header.moduleNames do
      if isTarget m then
        throw <| IO.userError s!"the target's outside imports load target module {m}"
    let _ ← Kernel.Environment.replay newConsts base.toKernelEnv
    return Json.mkObj [("ran", true), ("ok", true), ("ms", toJson (← elapsed t0)), ("load_ms", toJson tLoad),
      ("constants", toJson newConsts.size), ("base_imports", toJson imports.size), ("error", Json.null)]
  catch e =>
    return Json.mkObj [("ran", true), ("ok", false), ("ms", toJson (← elapsed t0)),
      ("constants", toJson newConsts.size), ("base_imports", toJson imports.size),
      ("error", toString e |>.take 4000 |>.toString)]

def run (reqPath outPath : String) : IO Unit := do
  let req ← IO.ofExcept <| (Json.parse (← IO.FS.readFile reqPath)).bind parseRequest
  -- the running `lean`'s own prefix (no subprocess, no PATH lookup) plus LEAN_PATH
  initSearchPath (← getBuildDir)
  -- reset the initializer-execution flag that the frontend set for this file
  withImporting (pure ())
  let t0 ← IO.monoMsNow
  let env ← importModules (req.modules.map ({ module := · })) {} (loadExts := false)
  let loadMs ← elapsed t0
  IO.eprintln s!"CheckEnv: loaded {env.header.moduleNames.size} modules in {loadMs} ms"
  let modNames := env.header.moduleNames
  let isTarget (m : Name) : Bool := req.targetPrefix.isPrefixOf m
  let targetIdxs := (Array.range modNames.size).filter fun i => isTarget modNames[i]!
  for m in req.modules do
    unless isTarget m do throw <| IO.userError s!"requested module {m} is outside {req.targetPrefix}"
  let modOf (n : Name) : Option Name := (env.getModuleIdxFor? n).map fun i => modNames[i.toNat]!
  let inScope (n : Name) : Bool :=
    req.closurePrefixes.any (·.isPrefixOf n) ||
      (modOf n).any fun m => req.closurePrefixes.any (·.isPrefixOf m)
  -- protected declarations
  let t1 ← IO.monoMsNow
  let mut prot : Array (String × Json) := #[]
  for n in req.protectedNames do
    match env.find? n with
    | none => prot := prot.push (n.toString, Json.mkObj [("exists", false)])
    | some ci =>
      let (axs, axMissing) := axiomsOf env n
      let closure := match closureOf env inScope req.maxClosureBytes n with
        | .ok c => Json.mkObj [("dump", c.dump), ("members", namesJ c.members), ("missing", namesJ c.missing),
                               ("error", Json.null)]
        | .error e => Json.mkObj [("dump", Json.null), ("error", e)]
      prot := prot.push (n.toString, Json.mkObj [
        ("exists", true), ("kind", kindStr ci), ("module", (modOf n).map nameJ |>.getD Json.null),
        ("level_params", namesJ ci.levelParams.toArray), ("closure", closure),
        ("axioms", namesJ axs), ("axioms_missing", namesJ axMissing)])
  let protMs ← elapsed t1
  IO.eprintln s!"CheckEnv: protected declarations in {protMs} ms"
  -- every constant of the target
  let t2 ← IO.monoMsNow
  let mut entries : Array (Name × Name × ConstantInfo × NameSet) := #[]
  let mut targetNames : NameSet := {}
  for i in targetIdxs do
    for ci in env.header.moduleData[i]!.constants do
      unless targetNames.contains ci.name do
        targetNames := targetNames.insert ci.name
        entries := entries.push (ci.name, modNames[i]!, ci, usedConsts ci)
  let mut uses : Std.HashMap Name Nat := {}
  for (n, _, _, refs) in entries do
    for r in refs do
      if r != n && targetNames.contains r then
        uses := uses.insert r (uses.getD r 0 + 1)
  let mut forbiddenSeen : NameSet := {}
  let mut out : Array (String × Json) := #[]
  for (n, m, ci, refs) in entries do
    let isForb (r : Name) : Bool := req.forbiddenPrefixes.any (·.isPrefixOf r) && !isProofConst env r
    -- those in the type first: they say best what the declaration is
    let tForb := (ci.type.getUsedConstantsAsSet.toArray.filter isForb).qsort Name.lt
    let forb := tForb ++ ((refs.toArray.filter fun r => isForb r && !tForb.contains r).qsort Name.lt)
    for p in req.forbiddenPrefixes do
      if forb.any (p.isPrefixOf ·) then forbiddenSeen := forbiddenSeen.insert p
    let range := match declRangeExt.find? (level := .exported) env n <|>
        declRangeExt.find? (level := .server) env n with
      | some r => Json.arr #[toJson r.range.pos.line, toJson r.range.endPos.line]
      | none => Json.null
    let kind := match ci with
      | .inductInfo _ => if isStructure env n then "structure" else "inductive"
      | _ => kindStr ci
    let mut fields : List (String × Json) := [
      ("k", kind), ("m", nameJ m), ("unsafe", ci.isUnsafe), ("partial", ci.isPartial),
      ("impl", (Compiler.getImplementedBy? env n).map nameJ |>.getD Json.null),
      ("extern", isExtern env n), ("meta", isMarkedMeta env n),
      ("forbidden", namesJ forb), ("range", range), ("uses", toJson (uses.getD n 0)),
      ("autoparam", isAutoParamSyntax req.autoParamRefs ci),
      ("wf_rec", isWfUnsafeRec env (fun f => modOf f == some m) ci)]
    -- a name the module system let two modules define (duplicate theorems)
    if modOf n != some m then
      fields := fields ++ [("home", (modOf n).map nameJ |>.getD Json.null)]
    if req.emitRefs then
      fields := fields ++ [("refs", namesJ (refs.toArray.qsort Name.lt))]
    out := out.push (n.toString, Json.mkObj fields)
  let sortedOut := out.qsort (fun a b => a.1 < b.1)
  -- target constants reachable from the protected declarations and the extra
  -- roots, through types and values (and inductive ↔ constructor/recursor)
  let mut byName : Std.HashMap Name (ConstantInfo × NameSet) := {}
  for (n, _, ci, refs) in entries do
    byName := byName.insert n (ci, refs)
  let mut reach : NameSet := {}
  let mut todo : Array Name := req.protectedNames ++ req.roots
  while h : todo.size > 0 do
    let n := todo[todo.size - 1]
    todo := todo.pop
    if reach.contains n then continue
    let some (ci, refs) := byName[n]? | continue
    reach := reach.insert n
    let extra : List Name := match ci with
      | .inductInfo v => v.ctors
      | .ctorInfo v => [v.induct]
      | .recInfo v => v.all
      | _ => []
    for r in refs do
      unless reach.contains r do todo := todo.push r
    for r in extra do
      unless reach.contains r do todo := todo.push r
  let reachable := (reach.toArray.map (·.toString)).qsort (· < ·)
  let scanMs ← elapsed t2
  IO.eprintln s!"CheckEnv: scanned {sortedOut.size} target constants in {scanMs} ms"
  let replay ← if req.replay then
      IO.eprintln "CheckEnv: kernel replay …"
      replayTarget env isTarget targetIdxs
    else pure (Json.mkObj [("ran", false), ("ok", Json.null), ("ms", Json.null)])
  if req.replay then IO.eprintln s!"CheckEnv: replay {replay.compress}"
  let result := Json.mkObj [
    ("schema", "concept-mining-checkenv/v1"),
    ("lean_version", Lean.versionString),
    ("target_prefix", nameJ req.targetPrefix),
    ("modules_loaded", toJson modNames.size),
    ("target_modules", toJson targetIdxs.size),
    ("protected", Json.mkObj prot.toList),
    ("constants", Json.mkObj sortedOut.toList),
    ("forbidden_prefixes_seen", namesJ forbiddenSeen.toArray),
    ("roots", namesJ (req.protectedNames ++ req.roots)),
    ("reachable", .arr (reachable.map Json.str)),
    ("replay", replay),
    ("ms", Json.mkObj [("load", toJson loadMs), ("protected", toJson protMs), ("scan", toJson scanMs)])]
  IO.FS.writeFile outPath result.compress

end GateCheck

def main (args : List String) : IO UInt32 := do
  match args with
  | [reqPath, outPath] =>
    try
      GateCheck.run reqPath outPath
      return 0
    catch e =>
      IO.eprintln s!"CheckEnv: error: {e}"
      return 1
  | _ =>
    IO.eprintln "usage: lean --run CheckEnv.lean <request.json> <out.json>"
    return 2
