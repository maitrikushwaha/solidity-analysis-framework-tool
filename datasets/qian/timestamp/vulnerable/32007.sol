pragma solidity ^0.4.25;

contract ReciveAndSend{

    function getHours() public returns (uint){
        return (block.timestamp / 60 / 60) % 24;
    }
}