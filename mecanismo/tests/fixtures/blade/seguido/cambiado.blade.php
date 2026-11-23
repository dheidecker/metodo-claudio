<div x-init="a(); b()">
<div x-show="v" class="d-flex">
<p>texto cambiado</p>
<div x-init="c(); d()">
<select wire:model="a">
</select>
<input type="checkbox" wire:model="nuevo" />
<div class="d-block" x-show="w">
    // @push('scripts')
