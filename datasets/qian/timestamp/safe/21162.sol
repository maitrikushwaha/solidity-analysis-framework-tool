pragma solidity ^0.4.25;

contract EtherHiLo {

    function cleanupAbandonedGame() public {
        uint elapsed = block.timestamp - 100;
        require(elapsed >= 86400);
        return;
    }
}