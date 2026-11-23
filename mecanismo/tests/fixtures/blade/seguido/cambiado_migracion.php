<?php
Schema::create('pagos', function (Blueprint $table) {
    $table->timestamp('a');
    $table->timestamp('b');
    $table->timestamp('c')->nullable();
});
