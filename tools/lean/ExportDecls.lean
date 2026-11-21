/-
Export the elaborated declarations of one folder of CFSG as TSV.

Used by tools/export_decls.py, which prepends `import` lines for every module
of the folder and sets the two options below. Run from the root of a built
checkout of AxiomMath/CFSG:

    lake env lean ExportDecls.lean

Columns: name, module, kind, start line, end line, type hash, value hash (for
definitions; theorems get 0 since proofs are irrelevant), binders (one item
per leading ∀-binder: binder info, P if its type is a proposition, hash of its
type with loose bound variables), and the constants of the same folder used
by the type or value; then the type hash after identifying copies of the same
definition (see `canonicalMap`), and the representative of the declaration
if it is such a copy.
-/
open Lean Meta

def kindOf : ConstantInfo → String
  | .thmInfo _ => "theorem" | .defnInfo _ => "def" | .axiomInfo _ => "axiom"
  | .opaqueInfo _ => "opaque" | .inductInfo _ => "inductive" | .ctorInfo _ => "ctor"
  | .recInfo _ => "rec" | .quotInfo _ => "quot"

def biChar : BinderInfo → String
  | .default => "e" | .implicit => "i" | .strictImplicit => "s" | .instImplicit => "c"

partial def binderDoms : Expr → Array (BinderInfo × Expr)
  | .forallE _ d b bi => #[(bi, d)] ++ binderDoms b
  | .mdata _ e => binderDoms e
  | _ => #[]

/-- Replace constants by their representatives and universe parameters by
positional names, so that copies of one definition hash alike. -/
def cmNormalize (m : NameMap Name) (ci : ConstantInfo) (e : Expr) : Expr :=
  let ls := (List.range ci.levelParams.length).map fun i => Level.param (Name.mkSimple s!"u{i}")
  (e.instantiateLevelParams ci.levelParams ls).replace fun
    | .const n us => (m.find? n).map fun c => .const c us
    | _ => none

/-- Representatives of definitions that agree after normalization, computed
to a fixpoint: definitions with the same normalized type and body are merged,
which can make further definitions agree. -/
def canonicalMap (inPfx : Name → Bool) : MetaM (NameMap Name) := do
  let env ← getEnv
  let defs := env.constants.map₁.toList.filterMap fun (n, ci) =>
    match ci with
    | .defnInfo d => if inPfx n && !n.isInternal then some (n, ci, d.value) else none
    | _ => none
  let mut m : NameMap Name := {}
  for _ in [0:8] do
    let mut rep : Std.HashMap (UInt64 × UInt64) Name := {}
    let mut m' : NameMap Name := {}
    for (n, ci, v) in defs do
      let k := ((cmNormalize m ci ci.type).hash, (cmNormalize m ci v).hash)
      match rep[k]? with
      | some r => m' := m'.insert n r
      | none => rep := rep.insert k n
    if m'.size == m.size then return m'
    m := m'
  return m

def exportDecls (pfx : Name) (out : System.FilePath) : MetaM Unit := do
  let env ← getEnv
  let h ← IO.FS.Handle.mk out .write
  let inPfx (n : Name) : Bool :=
    match env.getModuleIdxFor? n with
    | some idx => pfx.isPrefixOf (env.header.moduleNames[idx.toNat]!)
    | none => false
  let canon ← canonicalMap inPfx
  let mut count := 0
  for (n, ci) in env.constants.map₁.toList do
    unless inPfx n do continue
    let mod := env.header.moduleNames[(env.getModuleIdxFor? n).get!.toNat]!
    let (s, e) ← match ← findDeclarationRanges? n with
      | some r => pure (r.range.pos.line, r.range.endPos.line)
      | none => pure (0, 0)
    let vh : UInt64 := match ci with
      | .defnInfo d => d.value.hash
      | _ => 0
    let doms := binderDoms ci.type
    let props ← try
        forallTelescope ci.type fun xs _ => xs.mapM fun x => do isProp (← inferType x)
      catch _ => pure #[]
    let mut bs : Array String := #[]
    for i in [0:doms.size] do
      let (bi, d) := doms[i]!
      let p := if props.getD i false then "P" else ""
      bs := bs.push s!"{biChar bi}{p}{d.hash}"
    let uses := ci.getUsedConstantsAsSet.toList.filter inPfx
    h.putStrLn s!"{n}\t{mod}\t{kindOf ci}\t{s}\t{e}\t{ci.type.hash}\t{vh}\t{" ".intercalate bs.toList}\t{" ".intercalate (uses.map toString)}\t{(cmNormalize canon ci ci.type).hash}\t{(canon.find? n).getD Name.anonymous}"
    count := count + 1
  IO.println s!"exported {count} declarations to {out}"
