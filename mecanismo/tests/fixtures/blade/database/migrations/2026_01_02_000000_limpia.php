<?php

return new class extends Migration {
    public function up(): void
    {
        Schema::table('cartera', function (Blueprint $table) {
            $table->dateTime('pagado_en')->nullable();
            $table->timestamps();
        });
    }
};
