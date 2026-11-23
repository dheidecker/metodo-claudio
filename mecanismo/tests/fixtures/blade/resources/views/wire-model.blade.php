<select class="form-select"
        wire:model="estado">
    <option value="1">Uno</option>
</select>
<select wire:model.live="tipo">
    <option value="1">Uno</option>
</select>
<input type="checkbox" wire:model="activo" />
<input type="checkbox" wire:model.live="visible" />
<input type="text" wire:model="nombre" />
<select
    id="region"
    wire:model="region"
    wire:model="comuna">
</select>
