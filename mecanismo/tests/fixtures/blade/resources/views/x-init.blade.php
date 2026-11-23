<div x-data="panel()" x-init="init()">
<div x-data="{}" x-init="localStorage.removeItem('filtros'); cargar()">
<div x-init="if (abierto) { cerrar() }">
<span x-init="$watch('a', v => b = v)"></span>
<div x-init="a(); b()">
<div x-init="c(); d()">
