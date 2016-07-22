angular.module('aiddataDET')
.controller('OptionsCtrl', function ($scope, $rootScope, $log, $stateParams, queryFactory) {
  $scope.dataset = {};

  $scope.options = [
    {
      name: 'Extract Options',
      type: 'checkbox',
      loc: 'options.extract_types',
      dest: 'options.extract_types',
      pick: 'name',
      data: []
    },
    {
      name: 'Resources',
      type: 'checkbox',
      loc: 'resources',
      dest: 'files',
      pick: ['name', 'path'],
      data: []
    }
  ];

  $scope.toggleOption = function (isChecked, val, option) {
    $log.debug(isChecked, val, option);

    return isChecked ? queryFactory.toggleOptionOn(option.dest, val) :
      queryFactory.toggleOptionOff(option.dest, val);
  };

  $scope.getTimeStamp = function (date, format) {
    var timeFormatter = d3.timeFormat('%b %d, %Y');
    var timeParser = d3.timeParse(format),
        formDate = timeFormatter(timeParser(date));
    return formDate;
  };

  $scope.$on('$viewContentLoaded', function (event) {
    $scope.dataset = queryFactory.getDataset($stateParams.dataset);

    _.each($scope.options, function (opt) {
      mapOption(opt);
    });
  });


  $rootScope.$on('dataset:selected', function (e, data) {
    $scope.dataset = data;

    // queryFactory.setDataset(data.name, 'OptionsCtrl');
  });

  function mapOption (option) {
    option.data = _.chain($scope.dataset)
      .get(option.loc)
      .map(function (choice) {
        return _.isString(choice) ? { name: choice } : choice;
      })
      .value();
  }
});
