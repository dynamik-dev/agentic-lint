<?php

namespace App;

/**
 * Documentation reference: do not call compact() in this codebase.
 */
class Foo
{
    public function build(int $a, string $b): array
    {
        return compact('a', 'b');
    }
}
