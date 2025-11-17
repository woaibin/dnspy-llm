# Save-to-JSON Analysis Export (Well-Structured)

This repository extends dnSpy with a feature that exports a structured view of all loaded .NET modules to JSON. The data is designed to be easily consumed by tools and LLM-based workflows.

## How the Export Works

- The feature walks all loaded modules from the Assembly Explorer (`IDocumentTreeView.GetAllModuleNodes()`).
- For each module, it inspects all non-global types and their members using dnlib (`ModuleDef`, `TypeDef`, `FieldDef`, `MethodDef`, `PropertyDef`, `EventDef`).
- The collected model is serialized as JSON using `DataContractJsonSerializer`.

## JSON Shape

Root object:

```jsonc
{
  "Modules": [ /* array of AnalyzedModule */ ]
}
```

Each `AnalyzedModule`:

```jsonc
{
  "Name": "MyAssembly.dll",
  "AssemblyFullName": "MyAssembly, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null",
  "FileName": "C:\\path\\to\\MyAssembly.dll",
  "AssemblyReferences": [ "System.Private.CoreLib, Version=...", "System.Runtime, Version=..." ],
  "Types": [ /* array of AnalyzedType */ ]
}
```

Each `AnalyzedType`:

```jsonc
{
  "Name": "MyType",
  "Namespace": "MyNamespace.Sub",
  "FullName": "MyNamespace.Sub.MyType",
  "BaseType": "System.Object",
  "IsPublic": true,
  "IsAbstract": false,
  "IsSealed": false,
  "Fields": [ /* AnalyzedMember */ ],
  "Methods": [ /* AnalyzedMember */ ],
  "Properties": [ /* AnalyzedMember */ ],
  "Events": [ /* AnalyzedMember */ ]
}
```

Each `AnalyzedMember`:

```jsonc
{
  "MemberType": "method",  // "field" | "method" | "property" | "event"
  "Name": "DoWork",
  "FullName": "MyNamespace.Sub.MyType.DoWork(System.Int32)",
  "Signature": "System.Void(System.Int32)",
  "IsStatic": false,
  "IsPublic": true
}
```

This schema is the basis for the LLM chat integration: the in-memory form of this model is used as a searchable cache of modules, types, and members.***
