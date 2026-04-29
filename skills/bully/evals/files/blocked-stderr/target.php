<?php

namespace App;

class Foo
{
    public function build(int $a, string $b): array
    {
        return compact('a', 'b');
    }
}
