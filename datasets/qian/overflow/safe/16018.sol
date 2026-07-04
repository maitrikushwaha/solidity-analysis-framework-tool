pragma solidity ^0.4.25;

contract TeamToken  {

    uint64 public gameTime;

    function test() payable public {
        if (gameTime > 1514764800) {
            require(gameTime > block.timestamp);
        }
        return;
    }
}