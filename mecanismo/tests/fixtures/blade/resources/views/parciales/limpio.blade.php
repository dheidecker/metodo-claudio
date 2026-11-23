<div x-data="panel()" x-init="init()">
    <div x-show="abierto">
        <div class="d-flex">contenido</div>
    </div>
    <select wire:model.live="estado">
        <option value="1">Uno</option>
    </select>
    {{-- @include('parciales.menu') --}}
</div>
