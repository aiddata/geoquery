angular.module('aiddataDET')
.controller('HelpCtrl', function($scope, $rootScope, $log, info) {
  $scope.content = info.help;
});
