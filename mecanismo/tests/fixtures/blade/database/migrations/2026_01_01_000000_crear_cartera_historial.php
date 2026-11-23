<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::create('cartera_historial', function (Blueprint $table) {
            $table->id();
            $table->timestamp('registrado_en');
            $table->timestamp('revisado_en')->nullable();
            $table->timestamp('creado')->useCurrent();
            $table->timestamps();
            $table->dateTime('pagado_en');
            $table->timestamp('cerrado_en');
        });
    }
};
