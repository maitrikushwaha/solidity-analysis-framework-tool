pragma solidity ^0.4.25;

contract secondContract {

    uint timeWindow = 18;

    function BirthdayBoyClickHere() public view returns(string) {
        uint time = block.timestamp;
        require(time < timeWindow);
        return "Happy Birthday";
    }
}