pragma solidity ^0.4.25;

contract CrowdsaleRC {
    uint public createdTimestamp;

    function CrowdsaleRC () public {
        createdTimestamp = block.timestamp;
    }
}